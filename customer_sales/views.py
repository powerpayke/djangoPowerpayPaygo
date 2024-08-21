from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.core.paginator import Paginator
from .models import Customer, Sale
from .forms import CustomerForm, SaleForm
from datetime import timedelta
import requests
from requests.auth import HTTPBasicAuth
import json
from operator import itemgetter

# Constants
BASE_URL = "https://appliapay.com/"
AUTH = HTTPBasicAuth('admin', '123Give!@#')


# Existing customer views...

def customers_list(request):
    query = request.GET.get('q')
    if query:
        customers = Customer.objects.filter(name__icontains=query)
    else:
        customers = Customer.objects.all()
    paginator = Paginator(customers, 10)
    page = request.GET.get('page')
    customers = paginator.get_page(page)
    return render(request, 'customer_sales/customers_list.html', {'customers': customers, 'query': query})

def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    registration_time = customer.date + timedelta(hours=3)
    return render(request, 'customer_sales/customer_detail.html', {'customer': customer, 'registration_time': registration_time})
    
def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            return redirect('customer_detail', pk=customer.pk)
    else:
        form = CustomerForm(instance=customer)
    return render(request, 'customer_sales/customer_edit.html', {'form': form})

def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        customer.delete()
        return redirect('customers_list')
    return render(request, 'customer_sales/customer_delete.html', {'customer': customer})

def add_customer(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('customers_list')
    else:
        form = CustomerForm()
    return render(request, 'customer_sales/add_customer.html', {'form': form})

def sale_add(request, customer_id=None):
    customer = None
    if customer_id:
        customer = get_object_or_404(Customer, pk=customer_id)

    if request.method == 'POST':
        form = SaleForm(request.POST)
        if form.is_valid():
            sale = form.save(commit=False)
            if customer:
                sale.customer = customer
            sale.save()
            return redirect('customer_detail', pk=sale.customer.pk if sale.customer else 'sales_list')
    else:
        form = SaleForm(current_customer_id=customer_id if customer_id else None)
    return render(request, 'customer_sales/sale_add.html', {'form': form, 'customer': customer})

# New sales views...

def sales_list(request):
    query = request.GET.get('q')
    if query:
        sales = Sale.objects.filter(product_name__icontains=query)
    else:
        sales = Sale.objects.all()
    
    paginator = Paginator(sales, 10)  # Show 10 sales per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'customer_sales/sales_list.html', {'sales': page_obj, 'query': query})

def sale_detail(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    return render(request, 'customer_sales/sale_detail.html', {'sale': sale})

def sale_edit(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    if request.method == 'POST':
        form = SaleForm(request.POST, instance=sale)
        if form.is_valid():
            form.save()
            if sale.customer:
                return redirect('customer_detail', pk=sale.customer.pk)
            else:
                return redirect('sales_list')
    else:
        form = SaleForm(instance=sale)
    return render(request, 'customer_sales/sale_form.html', {'form': form})

def sale_delete(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    if request.method == 'POST':
        sale.delete()
        return redirect('sales_list')
    return render(request, 'customer_sales/sale_confirm_delete.html', {'sale': sale})


def fetch_data(endpoint):
    response = requests.get(BASE_URL + endpoint, auth=AUTH)
    response.raise_for_status()
    return response.json()
#######PAYGO
def paygo_sales(request):
    sort_field = request.GET.get('sort', 'product_serial_number')
    sort_direction = request.GET.get('direction', 'asc')
    query = request.GET.get('q', '')

    # Fetch sales data (assuming it's coming from an external source or model)
    sales_data = fetch_data('paygoScode')

    # Custom sorting function
    def sort_sales(data, sort_field, direction='asc'):
        def sort_key(sale):
            if sort_field == 'product_serial_number':
                # Sort by the last 4 digits of the serial number
                return int(sale['product_serial_number'][-4:])
            elif sort_field == 'payment_status':
                # Define a custom order for payment statuses
                status_order = {
                    'overdue': 0,
                    'on-time': 1,
                    'fully-paid': 2
                }
                return status_order.get(sale['paymentData']['payment_status'], 3)
            elif sort_field in ['totalPaid', 'paygoBalance', 'days', 'balance']:
                # Convert to float or int as necessary
                value = sale['paymentData'].get(sort_field, 0)
                try:
                    return float(value)  # Convert to float for consistency
                except ValueError:
                    return 0
            else:
                return sale.get(sort_field, '')

        reverse = direction == 'desc'
        return sorted(data, key=sort_key, reverse=reverse)


    # Apply custom sorting
    sorted_sales = sort_sales(sales_data, sort_field, sort_direction)

    # Add pagination or any other processing as needed
    paginator = Paginator(sorted_sales, 10)  # Show 10 sales per page
    page_number = request.GET.get('page')
    page_sales = paginator.get_page(page_number)

    context = {
        'sales': page_sales,
        'sort_field': sort_field,
        'sort_direction': sort_direction,
        'query': query,
    }
    return render(request, 'customer_sales/paygo_sales.html', context)

def paygo_sales_non_metered(request):
    sort_field = request.GET.get('sort', 'product_serial_number')
    sort_direction = request.GET.get('direction', 'asc')
    query = request.GET.get('q', '')

    # Fetch sales data (assuming it's coming from an external source or model)
    sales_data = fetch_data('paygoScodeNonMetered')

    # Custom sorting function
    def sort_sales(data, sort_field, direction='asc'):
        def sort_key(sale):
            if sort_field == 'product_serial_number':
                # Sort by the last 4 digits of the serial number
                return int(sale['product_serial_number'][-4:])
            elif sort_field == 'payment_status':
                # Define a custom order for payment statuses
                status_order = {
                    'overdue': 0,
                    'on-time': 1,
                    'fully-paid': 2
                }
                return status_order.get(sale['paymentData']['payment_status'], 3)
            elif sort_field in ['totalPaid', 'paygoBalance', 'days', 'balance']:
                # Convert to float or int as necessary
                value = sale['paymentData'].get(sort_field, 0)
                try:
                    return float(value)  # Convert to float for consistency
                except ValueError:
                    return 0
            else:
                return sale.get(sort_field, '')

        reverse = direction == 'desc'
        return sorted(data, key=sort_key, reverse=reverse)


    # Apply custom sorting
    sorted_sales = sort_sales(sales_data, sort_field, sort_direction)

    # Add pagination or any other processing as needed
    paginator = Paginator(sorted_sales, 10)  # Show 10 sales per page
    page_number = request.GET.get('page')
    page_sales = paginator.get_page(page_number)

    context = {
        'sales': page_sales,
        'sort_field': sort_field,
        'sort_direction': sort_direction,
        'query': query,
    }
    return render(request, 'customer_sales/paygo_sales_non_metered.html', context)
