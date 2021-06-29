# Generated by Django 3.0.3 on 2021-06-07 09:21

from django.db import migrations, models
import encrypted_fields.fields


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='JiraConnection',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label', models.CharField(blank=True, max_length=200, verbose_name='Label')),
                ('api_url', models.CharField(max_length=200, verbose_name='API URL')),
                ('username', models.CharField(blank=True, max_length=200, verbose_name='API Username')),
                ('password', encrypted_fields.fields.EncryptedCharField(blank=True, max_length=200, verbose_name='Password')),
                ('story_points_field', models.CharField(max_length=200, verbose_name='Story Points Field')),
            ],
            options={
                'verbose_name': 'Jira Connection',
                'verbose_name_plural': 'Jira Connections',
            },
        ),
    ]