# admin.py
from django.contrib import admin
from .models import Customer, Sale

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'id_number', 'phone_number')

@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('product_name', 'product_model', 'customer', 'registration_date')
