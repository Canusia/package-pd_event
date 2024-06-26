# Generated by Django 4.2 on 2024-04-20 18:17

import cis.storage_backend
import cis.utils
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('cis', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Event',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(blank=True, max_length=100, null=True)),
                ('start_time', models.DateTimeField(blank=True, null=True, verbose_name='Start Date & Time')),
                ('end_time', models.DateTimeField(blank=True, null=True, verbose_name='End Date & Time')),
                ('created_on', models.DateTimeField(auto_now=True)),
                ('description', models.TextField(blank=True, null=True)),
                ('pd_hour', models.FloatField(default=0.0, null=True, verbose_name='PD Hour(s)')),
                ('delivery_mode', models.CharField(blank=True, choices=[('', 'Select'), ('In Person', 'In Person'), ('Online', 'Online'), ('Hybrid', 'Hybrid')], max_length=10, null=True, verbose_name='Delivery Mode')),
                ('cohort', models.JSONField(blank=True, null=True, verbose_name='Cohort(s)')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='EventType',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=100)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='EventFile',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('description', models.TextField(blank=True, null=True)),
                ('media', models.FileField(storage=cis.storage_backend.PrivateMediaStorage(), upload_to=cis.utils.event_file_upload_path)),
                ('uploaded_on', models.DateTimeField(auto_now=True)),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='pd_event.event')),
            ],
        ),
        migrations.AddField(
            model_name='event',
            name='event_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='pd_event.eventtype', verbose_name='Event Type'),
        ),
        migrations.AddField(
            model_name='event',
            name='term',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='cis.term'),
        ),
        migrations.CreateModel(
            name='EventAttendee',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('type', models.CharField(choices=[('instructor', 'Instructor'), ('highschool', 'High School'), ('faculty', 'Faculty')], max_length=50)),
                ('meta', models.JSONField(blank=True, null=True)),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pd_event.event')),
            ],
            options={
                'unique_together': {('event', 'meta')},
            },
        ),
    ]
