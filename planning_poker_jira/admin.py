from typing import Dict, List, Union

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers, ModelAdmin
from django.contrib.admin.templatetags.admin_urls import admin_urlname
from django.contrib.admin.utils import unquote
from django.db.models import QuerySet
from django.http import HttpResponse, HttpResponseRedirect, HttpRequest
from django.template.response import TemplateResponse
from django.urls import reverse, URLResolver, URLPattern
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _, ngettext_lazy
from jira import JIRA, JIRAError

from planning_poker.admin import StoryAdmin
from planning_poker.models import PokerSession

from .models import JiraConnection


def export_stories(modeladmin: ModelAdmin, request: HttpRequest, queryset: QuerySet) -> Union[HttpResponse, None]:
    """Send the story points for each story in the queryset to the selected backend.

    :param ModelAdmin modeladmin: The current ModelAdmin.
    :param HttpRequest request: The current HTTP request.
    :param QuerySet queryset: Containing the set of stories selected by the user.
    :return: A http response which either redirects back to the changelist view on success or renders a template with
             the `ExportStoriesForm`.
    :rtype: HttpResponse or None
    """
    if 'export' in request.POST:
        form = ExportStoriesForm(request.POST)
        if form.is_valid():
            jira_connection = form.cleaned_data['jira_connection']
            client = form.client
            try:
                for story in queryset:
                    jira_story = client.issue(id=story.ticket_number, fields='')
                    jira_story.update(fields={jira_connection.story_points_field: story.story_points})
            except JIRAError:
                modeladmin.message_user(
                    request,
                    _('The story "{}" could not be exported '
                      'because it probably does not exist in "{}"').format(story, jira_connection),
                    messages.ERROR
                )
            else:
                num_stories = len(queryset)
                modeladmin.message_user(request, ngettext_lazy(
                    '%d story was successfully exported.',
                    '%d stories were successfully exported.',
                    num_stories,
                ) % num_stories, messages.SUCCESS)
            return None
    else:
        form = ExportStoriesForm()
    admin_form = helpers.AdminForm(
        form,
        (
            (None, {
                'fields': ('jira_connection',)
            }),
            (_('Override Options'), {
                'fields': ('username', 'password')
            }),
        ),
        {},
        model_admin=modeladmin
    )
    context = {
        **modeladmin.admin_site.each_context(request),
        'opts': queryset.model._meta,
        'title': _('Export Stories'),
        'stories': queryset,
        'form': admin_form,
        'media': modeladmin.media
    }
    return TemplateResponse(request, 'admin/planning_poker/story/export_stories.html', context)


class JiraAuthenticationForm(forms.Form):
    username = forms.CharField(label=_('Username'),
                               help_text=_('You can use this to override the username saved in the database'),
                               required=False)
    password = forms.CharField(label=_('Password'),
                               help_text=_('You can use this to override the password in the database'),
                               required=False,
                               widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        self.connection = kwargs.pop('connection', None)
        self.client = kwargs.pop('client', None)
        super().__init__(*args, **kwargs)

    def clean(self) -> dict:
        cleaned_data = super().clean()

        if connection := cleaned_data.get('jira_connection'):
            self.connection = connection
        api_url = cleaned_data.get('api_url') or getattr(self.connection, 'api_url', None)
        username = cleaned_data.get('username') or getattr(self.connection, 'username', None)
        password = cleaned_data.get('password') or getattr(self.connection, 'password', None)
        if not (api_url and username):
            self.add_error(None,
                           _('Missing credentials. Check whether you entered an API URL, an username and a password'))
        # We don't have to verify the credentials if the user hasn't provided a password.
        if password:
            try:
                self.client = JIRA(api_url, basic_auth=(username, password))
            except JIRAError as e:
                if e.status_code == 401:
                    error_message = _('Could not authenticate the API user with the given credentials. '
                                      'Make sure that you entered the correct data.')
                else:
                    error_message = e.status_code
                self.add_error(None, error_message)
        return cleaned_data


class JiraConnectionForm(JiraAuthenticationForm, forms.ModelForm):
    username = forms.CharField(label=_('Username'),
                               required=False)
    password = forms.CharField(label=_('Password'),
                               required=False,
                               widget=forms.PasswordInput)


class ImportStoriesForm(JiraAuthenticationForm):
    poker_session = forms.ModelChoiceField(
        label=_('Poker Session'),
        help_text=_('The poker session to which the imported stories should be added'),
        queryset=PokerSession.objects.all(),
        required=False
    )
    jql_query = forms.CharField(label=_('JQL Query'), required=True)


class ExportStoriesForm(JiraAuthenticationForm):
    jira_connection = forms.ModelChoiceField(
        label=_('Jira Connection'),
        help_text=_('The Jira Backend to which the stories should be exported'),
        queryset=JiraConnection.objects.all(),
        required=True
    )


@admin.register(JiraConnection)
class JiraConnectionAdmin(admin.ModelAdmin):
    form = JiraConnectionForm
    fields = ('label', 'api_url', 'username', 'password', 'story_points_field')
    list_display = ('__str__', 'get_import_stories_url')

    def get_urls(self) -> List[Union[URLResolver, URLPattern]]:
        from django.urls import path

        urls = super().get_urls()

        import_stories_path = path('<path:object_id>/import_stories/',
                                   self.admin_site.admin_view(self.import_stories_view),
                                   name='_'.join((self.opts.app_label, self.opts.model_name, 'import_stories')))

        urls.insert(0, import_stories_path)
        return urls

    def get_import_stories_url(self, obj: JiraConnection) -> str:
        """Create a small anchor tag with the link to the object's import stories view.

        :param JiraConnection obj: The jira connection which should be used to determine the url.
        :return: A string containing a html anchor tag where the href attribute points to the import stories view.
        :rtype: str
        """
        import_stories_url = reverse(admin_urlname(obj._meta, 'import_stories'), args=[obj.id])
        return format_html('<a href="{}">{}</a>', import_stories_url, _('Import'))
    get_import_stories_url.short_description = _('Import Stories')

    def import_stories_view(self, request: HttpRequest, object_id: int, extra_context: Dict = None) -> HttpResponse:
        """Render a view where the user can import stories from a jira connection.

        :param HTTPRequest request: The current HTTPRequest.
        :param int object_id: The id of the jira connection which should be used to import the stories.
        :param Dict extra_context: Additional context which should be added to the view.
        :return: A http response which either redirects back to the changelist view on success or renders a template
                 with the `ImportStoriesForm`.
        :rtype: HttpResponse
        """
        obj = self.get_object(request, unquote(object_id))

        if obj is None:
            return self._get_obj_does_not_exist_redirect(request, self.model._meta, object_id)

        if request.method == 'POST':
            form = ImportStoriesForm(request.POST, connection=obj)
            if form.is_valid():
                try:
                    stories = obj.create_stories(form.cleaned_data['jql_query'],
                                                 form.cleaned_data['poker_session'],
                                                 form.client)
                except JIRAError as e:
                    error_text = e.text if e.status_code == 400 else e.status_code
                    form.add_error('jql_query', error_text)
                else:
                    num_stories = len(stories)
                    self.message_user(request, ngettext_lazy(
                        '%d story was successfully imported.',
                        '%d stories were successfully imported.',
                        num_stories,
                    ) % num_stories, messages.SUCCESS)
                    redirect_url = f'admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist'
                    return HttpResponseRedirect(reverse(redirect_url))
        else:
            form = ImportStoriesForm(connection=obj)
        admin_form = helpers.AdminForm(
            form,
            (
                (None, {
                    'fields': ('poker_session', 'jql_query')
                }),
                (_('Override Options'), {
                    'fields': ('username', 'password'),
                }),
            ),
            {},
            model_admin=self
        )
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': _('Import stories from {}').format(obj),
            'form': admin_form,
            'object_id': object_id,
        }
        context.update(extra_context or {})
        return TemplateResponse(request, 'admin/planning_poker_jira/jira_connection/import_stories.html', context)


StoryAdmin.add_action(export_stories, _('Export Stories to Jira'))
