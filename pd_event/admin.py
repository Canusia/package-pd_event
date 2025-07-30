from django.contrib import admin

# Register your models here.

from django.contrib import admin
from .models import Venue, InfoSession

@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'state', 'zip')
    search_fields = ('name', 'city', 'state', 'zip')

@admin.register(InfoSession)
class InfoSessionAdmin(admin.ModelAdmin):
    list_display = ['term']
