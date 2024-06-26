# Generated by Django 4.2 on 2024-04-23 00:01

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pd_event', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='meta',
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
        migrations.AlterField(
            model_name='event',
            name='cohort',
            field=models.JSONField(blank=True, null=True, verbose_name='Subject(s)'),
        ),
    ]
