from django.contrib import admin

from search.models import FarmersMarket, HealthyStore, MenuItem

admin.site.register([MenuItem, FarmersMarket, HealthyStore])
