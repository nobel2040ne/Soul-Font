# Generated by Django 3.2.18 on 2025-05-06 16:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pybo', '0006_auto_20250506_1632'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='userdata',
            name='templates',
        ),
        migrations.AddField(
            model_name='userdata',
            name='template1',
            field=models.ImageField(blank=True, null=True, upload_to='templates/'),
        ),
        migrations.AddField(
            model_name='userdata',
            name='template2',
            field=models.ImageField(blank=True, null=True, upload_to='templates/'),
        ),
        migrations.AddField(
            model_name='userdata',
            name='template3',
            field=models.ImageField(blank=True, null=True, upload_to='templates/'),
        ),
    ]
