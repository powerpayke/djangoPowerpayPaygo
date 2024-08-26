from django.shortcuts import render, redirect
import requests
from requests.auth import HTTPBasicAuth
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta
import plotly.io as pio
from django.core.paginator import Paginator
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from django.http import HttpResponse

# Constants
BASE_URL = "https://appliapay.com/"
AUTH = HTTPBasicAuth('admin', '123Give!@#')
# At the top of your views.py file
payment_status = {
    "status": "pending",
    "message": "",
    "amount": None,
    "receipt_number": None,
    "transaction_date": None,
    "phone_number": None
}


def fetch_data(endpoint):
    response = requests.get(BASE_URL + endpoint, auth=AUTH)
    response.raise_for_status()
    return response.json()

def fetch_data_index(endpoint, range):
    response = requests.get(BASE_URL + endpoint+"?range="+str(range), auth=AUTH)
    response.raise_for_status()
    return response.json()


def login_page(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('home_page')
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'login.html')

def logout_page(request):
    logout(request)
    return redirect('login')

@login_required
def homepage(request):
    usr = request.user.username
    range = request.GET.get('range', 9999999)

    def fetch_and_process_data(range):
        if usr == 'John-Maina':
            data = fetch_data_index("allDeviceDataScodeDjango", range)
        else:
            data = fetch_data_index("allDeviceDataDjango", range)

        # Check if the data response is empty
        if data['totalkwh'] == 0 and data['runtime'] == 0 and not data['rawData']:
            return None

        runtime = data['runtime']
        raw_data = data['rawData']
        df = pd.DataFrame(raw_data)
        data_list = df.to_dict(orient='records')
        meals, mls = classify_and_count_meals(data_list)
        morning, afternoon, night = categorize_kwh(data_list)
        #scatterCharts = plotAllDevData(df)
        return runtime, data_list, meals, morning, afternoon, night
    
    processed_data = fetch_and_process_data(range)

    # If no data is returned, refetch with default range
    if not processed_data:
        messages.warning(request, 'No data for the selected range. Showing default data.')
        range = 9999999
        processed_data = fetch_and_process_data(range)
    
    runtime, data_list, meals, morning, afternoon, night = processed_data

    meal_counts = [info['count'] for device_id, info in meals.items()]
    sumKwh = sum(x['kwh'] for x in data_list)
    sumRuntime = sum(runtime.values())
    sumMeals = sum(meal_counts)

    charts = generate_charts(data_list, runtime, meals, morning, afternoon, night)

    context = {
        'line_chart': charts['line_chart'],
        'pie_chart': charts['pie_chart'],
        'meals_pie_html': charts['meals_pie_html'],
        'meals_kwh_html': charts['meals_kwh_html'],
        'cooking_time_pie_html': charts['cooking_time_pie_html'],
        'meals_emissions_html': charts['meals_emissions_html'],
        'pie_chart_emissions': charts['pie_chart_emissions'],
        'sumKwh': sumKwh,
        'sumRuntime': sumRuntime,
        'sumEmissions': sumKwh * 0.28 * 0.4999,
        'sumEnergyCost': sumKwh * 23.0,
        'sumMeals': sumMeals,
        'selected_range': str(range),
        'meals': meals
        #'scatter_chart': scatterCharts
    }

    return render(request, 'index.html', context)

def plotAllDevData(data):
    # Convert txtime to datetime format
    data['txtime'] = pd.to_datetime(data['txtime'], format='%Y%m%d%H%M%S')

    fig = go.Figure()

    # Create scatter plots for each unique deviceID
    for device_id in data['deviceID'].unique():
        device_data = data[data['deviceID'] == device_id]
        
        fig.add_trace(go.Scatter(
            x=device_data['txtime'],
            y=(device_data['kwh']*1000),
            mode='lines+markers',
            name=device_id,
            line_shape='spline'
        ))

    fig.update_traces(hovertemplate='Date: %{x}<br>Energy: %{y} Wh')

    fig.update_layout(
        title='Scatter plot for all devices',
        xaxis_title='Date',
        yaxis_title='KWH',
        showlegend=True,
        autosize=True,
        title_x=0.5,
        height=500,
        margin=dict(l=20, r=20, t=40, b=20)
    )

    # Convert the figure to HTML
    fig_html = pio.to_html(fig, full_html=False)
    
    return fig_html


@login_required
def devices_page(request):
    usr = request.user.username
    if usr == 'John-Maina':
        data = fetch_data("commandScode")
    else:
        data = fetch_data("command")
    data = pd.DataFrame(data)
    if not data.empty:
        # Sorting and handling different naming conventions
        def sort_key(x):
            if x == 'OfficeFridge1':
                return float('inf')
            elif x.startswith('device'):
                return int(x.split('device')[-1])
            elif x.startswith('JD-'):
                return int(x.split('JD-29ED')[-1])
            else:
                return float('inf') - 1
        
        data['sort_key'] = data['deviceID'].apply(sort_key)
        data = data.sort_values(by='sort_key')

        # Convert 'time' to datetime format
        data['time'] = pd.to_datetime(data['time'], format="%Y-%m-%dT%H:%M:%S.%fZ")

        # Handle search query
        query = request.GET.get('q')
        if query:
            data = data[data['deviceID'].str.lower().str.contains(query.lower())]

        # Convert the DataFrame to a list of dictionaries
        devices_list = data.to_dict(orient='records')

        # Implement pagination with 10 items per page
        paginator = Paginator(devices_list, 10)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
    else:
        page_obj = []

    device_list = [device['deviceID'] for device in devices_list]

    context = {
        'devices_table': page_obj,
        'query': query,
        'device_list': device_list  # Add the device list to the context
    }

    return render(request, 'devices.html', context)


def classify_and_count_meals(data):
    sorted_data = sorted(data, key=lambda x: (x['deviceID'], x['txtime']))
    device_meal_counts = {}
    day_meal_counts = {}

    for entry in sorted_data:
        if entry['deviceID'] != 'OfficeFridge1':
            device_id = entry['deviceID']
            txtime = datetime.strptime(str(entry['txtime']), "%Y%m%d%H%M%S")

            if device_id not in device_meal_counts:
                device_meal_counts[device_id] = {'count': 0, 'last_txtime': None}
            if device_meal_counts[device_id]['last_txtime'] is not None:
                time_diff = txtime - device_meal_counts[device_id]['last_txtime']
                if time_diff > timedelta(minutes=20):
                    device_meal_counts[device_id]['count'] += 1
            else:
                device_meal_counts[device_id]['count'] += 1

            date = txtime.strftime('%Y-%m-%d')
            if date not in day_meal_counts:
                day_meal_counts[date] = {}
            if device_id not in day_meal_counts[date]:
                day_meal_counts[date][device_id] = 0
            if 'last_txtime' in day_meal_counts[date]:
                time_diff = txtime - day_meal_counts[date]['last_txtime']
                if time_diff > timedelta(minutes=20):
                    day_meal_counts[date][device_id] += 1
            else:
                day_meal_counts[date][device_id] += 1
            
            device_meal_counts[device_id]['last_txtime'] = txtime
            day_meal_counts[date]['last_txtime'] = txtime

    total_meals_per_day = {date: sum(count for device, count in counts.items() if device != 'last_txtime') for date, counts in day_meal_counts.items()}
    return device_meal_counts, total_meals_per_day

def categorize_kwh(data):
    morning_kwh = 0
    afternoon_kwh = 0
    night_kwh = 0
    for record in data:
        hour = int(str(record['txtime'])[8:10])
        if 4 <= hour < 11:
            morning_kwh += record['kwh']
        elif 11 <= hour < 17:
            afternoon_kwh += record['kwh']
        else:
            night_kwh += record['kwh']
    return morning_kwh, afternoon_kwh, night_kwh

def generate_charts(data, runtime, meals, morning, afternoon, night):
    # Convert data to DataFrame
    df = pd.DataFrame(data)
    df['txtime'] = pd.to_datetime(df['txtime'], format='%Y%m%d%H%M%S')
    df = df[df['kwh'] >= 0]

    device_ids = [device_id for device_id, info in meals.items()]
    meal_counts = [info['count'] for device_id, info in meals.items()]
    runtime_device_ids = list(runtime.keys())
    runtime_hours = list(runtime.values())

    # Create Pie Charts
    cooking_time_pie = create_pie_chart(runtime_device_ids, runtime_hours, 'Cooking Time by Device')
    meals_pie = create_pie_chart(device_ids, meal_counts, 'Meals Distribution by Device')
    kwh_pie = create_pie_chart(["Breakfast", "Lunch", "Supper"], [morning, afternoon, night], 'KWH Per Meal')
    emissions_pie = create_pie_chart(["Breakfast", "Lunch", "Supper"], [morning * 0.4999 * 0.28, afternoon * 0.4999 * 0.28, night * 0.4999 * 0.28], 'Emissions Per Meal')

    # Line Chart
    energy_line_chart = create_line_chart(df, 'txtime', 'kwh', 'Energy Consumption')

    # Device kWh Pie Chart
    df_pie = df.groupby('deviceID')['kwh'].sum().reset_index()
    kwh_pie_chart = create_pie_chart(df_pie['deviceID'], df_pie['kwh'], 'kWh Distribution by Device')

    # Emissions per Device Pie Chart
    df_pie_emissions = df.copy()
    df_pie_emissions['emissions'] = df_pie_emissions['kwh'] * 0.4999 * 0.28
    emissions_device_pie_chart = create_pie_chart(df_pie_emissions['deviceID'], df_pie_emissions['emissions'], 'Carbon Emissions Per Device')
    cooking_time_pie.update_traces(hovertemplate='<b>%{label}: %{value} hours', hole=.5)
    meals_pie.update_traces(hovertemplate='<b>%{label}: %{value} meals', hole=.5)
    kwh_pie.update_traces(hovertemplate='<b>%{label}: %{value} kWh', hole=.5)
    kwh_pie_chart.update_traces(hovertemplate='<b>%{label}: %{value} kWh', hole=.5)
    emissions_pie.update_traces(hovertemplate='<b>%{label}: %{value} kg CO₂', hole=.5)
    emissions_device_pie_chart.update_traces(hovertemplate='<b>%{label}: %{value} kg CO₂', hole=.5)

    return {
        'line_chart': pio.to_html(energy_line_chart, full_html=False),
        'pie_chart': pio.to_html(kwh_pie_chart, full_html=False),
        'meals_pie_html': pio.to_html(meals_pie, full_html=False),
        'meals_kwh_html': pio.to_html(kwh_pie, full_html=False),
        'cooking_time_pie_html': pio.to_html(cooking_time_pie, full_html=False),
        'meals_emissions_html': pio.to_html(emissions_pie, full_html=False),
        'pie_chart_emissions': pio.to_html(emissions_device_pie_chart, full_html=False)
    }

def create_pie_chart(names, values, title):
    pie_chart = px.pie(names=names, values=values, title=title)
    pie_chart.update_traces(textposition='inside', hoverinfo='label+value+percent',
                            hovertemplate='<b>%{label}: %{value}</b>')
    pie_chart.update_layout(
        showlegend=True,
        autosize=True,
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
        title_x=0.5
    )
    #pie_chart.update_layout(legend=dict(
    #orientation="v",
    #yanchor="bottom",
    #y=0.01,
    #xanchor="left",
    #x=0.01
    #))
    return pie_chart

def create_line_chart(df, x_column, y_column, title):
    # Create the bar chart
    bar_chart = px.bar(df, x=x_column, y=y_column, title=title, labels={x_column: 'Time', y_column: 'kWh'})

    # Update the trace for better visibility
    bar_chart.update_traces(
        marker=dict(color="#0ead00"),
        hovertemplate='%{x}<br>%{y} kWh<br>Device ID: %{text}',
        text=df['deviceID'],
        width=0.8  # Adjust width if needed
    )

    # Update layout for better visualization
    bar_chart.update_layout(
        xaxis_title='Time',
        yaxis_title='kWh',
        showlegend=False,
        autosize=True,
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
        title_x=0.5
    )

    return bar_chart

@login_required
def transactions_page(request):
    usr = request.user.username
    if usr == 'John-Maina':
        data = fetch_data("mpesarecordsscode")
    else:
        data = fetch_data("mpesarecords")
    data = pd.DataFrame(data)
    # Convert 'transtime' to datetime format
    data['transtime'] = pd.to_datetime(data['transtime'], format='%Y%m%d%H%M%S')

    # Sort the data by 'transtime' in descending order
    data = data.sort_values(by='transtime', ascending=False)

    # Handle search query
    query = request.GET.get('q')
    if query:
        data = data[data.apply(lambda row: query.lower() in row['name'].lower() or
                                            query.lower() in row['ref'].lower() or
                                            query.lower() in row['id'].lower(), axis=1)]

    # Convert the DataFrame to a list of dictionaries
    transactions_list = data.to_dict(orient='records')
    # Implement pagination with 10 items per page
    paginator = Paginator(transactions_list, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Line chart data
    line_chart_data = data[['transtime', 'amount']].sort_values(by='transtime')

    # Plotting the line chart
    fig_line = px.line(line_chart_data, x='transtime', y='amount', title='Amount Over Time', labels={'transtime': 'Transaction Time', 'amount': 'Amount'}, line_shape='spline')
    fig_line.update_traces(line=dict(color="#0ead00"), hovertemplate='%{x}<br>Amount: %{y}', mode='lines+markers')
    fig_line.update_traces(text=data['id'])  # Pass the transaction ID as text for hover template
    fig_line.update_layout(
        xaxis_title='Transaction Time',
        yaxis_title='Amount',
        showlegend=False,
        autosize=True,
        title_x = 0.5,
        height=400,
        #width=0.7 * 800,  # Assuming an 800px base width
        margin=dict(l=20, r=20, t=40, b=20)
    )
    line_chart = pio.to_html(fig_line, full_html=False)

    context = {
        'transactions_table': page_obj,  # Pass the page object to the template
        'query': query,  # Pass the query to the template to preserve it in the search box
        'line_chart': line_chart,  # Pass the line chart HTML to the template
    }

    return render(request, 'transactions.html', context)

def fetch_data_with_params(endpoint, dev, range_value):
    response = requests.get(BASE_URL + endpoint +"?device="+dev+"&range=" + str(range_value), auth=AUTH)
    response.raise_for_status()
    return response.json()

#######################################################STK PAYMENT CODE############################################################################


def post_payment_prompt(endpoint, contact, amount, ref):
    data = {"contact": contact, "ref": ref, "amount":amount}
    response = requests.post(BASE_URL + endpoint, json=data, auth=AUTH)
    response.raise_for_status()
    return response.json()

def payment_prompt_action(usr, contact, amount, ref):
    global payment_status
    payment_status = {
    "status": "pending",
    "message": "",
    "amount": None,
    "receipt_number": None,
    "transaction_date": None,
    "phone_number": None
    }
    if usr == 'John-Maina':
        res = post_payment_prompt(endpoint="stkpushscode", contact=contact, amount=amount, ref=ref)
    else:
        res = post_payment_prompt(endpoint="stkpush", contact=contact, amount=amount, ref=ref)
    return res

@login_required
def payment_prompt(request):
    usr = request.user.username
    global ref

    if request.method == 'POST':
        contact = request.POST.get('contact')
        amount = request.POST.get('amount')
        ref = request.POST.get('ref')
        try:
            res = payment_prompt_action(contact=contact, amount=amount, ref=ref, usr=usr)
            if res.get('ResponseCode') == 0:
                messages.info(request, res.get('ResponseDescription'))
                return redirect('payment_waiting', ref=ref)
            else:
                messages.error(request, "Failed. Kindly try again.")
        except requests.RequestException as e:
            messages.error(request, f"Error: {e}")
        return render(request, "payment_prompt.html")
    
    elif request.method == 'GET':
        ref = request.GET.get('ref')
        amount = request.GET.get('amount')
        contact = ""  # You may fetch this from the database using the ref or other logic
        return render(request, "payment_prompt.html", {'ref': ref, 'amount': amount, 'contact': contact})

    return render(request, "payment_prompt.html")



@csrf_exempt
def payment_confirmation(request):
    global payment_status  # Use the global variable
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            stk_callback = data.get('Body', {}).get('stkCallback', {})
            result_code = stk_callback.get('ResultCode')
            result_desc = stk_callback.get('ResultDesc')

            if result_code == 0:
                status = 'success'
                message = result_desc
                callback_metadata = stk_callback.get('CallbackMetadata', {}).get('Item', [])
                amount = next((item.get('Value') for item in callback_metadata if item.get('Name') == 'Amount'), None)
                receipt_number = next((item.get('Value') for item in callback_metadata if item.get('Name') == 'MpesaReceiptNumber'), None)
                transaction_date = next((item.get('Value') for item in callback_metadata if item.get('Name') == 'TransactionDate'), None)
                phone_number = next((item.get('Value') for item in callback_metadata if item.get('Name') == 'PhoneNumber'), None)
            else:
                status = 'failed'
                message = 'The user cancelled the request'
                amount = None
                receipt_number = None
                transaction_date = None
                phone_number = None

            # Update the global variable
            payment_status.update({
                "status": status,
                "message": message,
                "amount": amount,
                "receipt_number": receipt_number,
                "transaction_date": transaction_date,
                "phone_number": phone_number
            })
            print('Updated payment status:', payment_status)

            return JsonResponse({"status": status, "message": message})
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
    else:
        return JsonResponse({"error": "Method not allowed"}, status=405)

# Handle the payment confirmation status check
def payment_confirmation_page(request):
    global payment_status  # Use the global variable
    
    context = {
        'status': payment_status.get('status'),
        'message': payment_status.get('message'),
        'amount': payment_status.get('amount'),
        'receipt_number': payment_status.get('receipt_number'),
        'transaction_date': payment_status.get('transaction_date'),
        'phone_number': payment_status.get('phone_number')
    }

    return render(request, 'payment_confirmation.html', context)


@csrf_exempt
def payment_confirmation_status(request):
    global payment_status  # Use the global variable
    if request.method == 'GET':
        ref = request.GET.get('ref')
        print('Retrieved payment_status:', payment_status)
        status = payment_status.get('status')
        if status != 'pending':
            message = payment_status.get('message')
            return JsonResponse({'status': status, 'message': message})
        else:
            return JsonResponse({'status': 'pending', 'message': 'Payment is still pending.'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=405)


# Render the payment waiting page
def payment_waiting(request, ref):
    return render(request, "payment_waiting.html", {"ref": ref})


##########################################################END OF STK PAYMENT CODE#################################################################  


@login_required
def device_data_page(request, device_id):
    range_value = request.GET.get('range', 9999999)
    
    # Fetch data based on device_id and range_value
    data = fetch_data_with_params("deviceDataDjangoo", device_id, range_value)
    runtime = data['runtime']
    sum_kwh = data['sumKwh']
    emissions = sum_kwh * 0.4999 * 0.28
    energy_cost = sum_kwh * 23.0
    meals_with_durations = data['mealsWithDurations'][::-1]
    total_meals_per_day = data['totalMealsPerDay']

    # Convert the 'Date' keys to datetime
    total_meals_per_day = {pd.to_datetime(k): v for k, v in total_meals_per_day.items()}

    # Create DataFrame for total meals per day
    df_meals = pd.DataFrame(list(total_meals_per_day.items()), columns=["Date", "Meals"])
    fig_meals_bar = px.bar(df_meals, x="Date", y="Meals", title="Total Meals Per Day", labels={"Meals": "Number of Meals"})
    fig_meals_bar.update_traces(marker=dict(color="#0ead00"), hovertemplate='Date: %{x}<br>Number of Meals: %{y}')
    fig_meals_bar.update_layout(
        xaxis_title='Date',
        yaxis_title='Meals',
        showlegend=False,
        autosize=True,
        title_x=0.5,
        height=400,
        margin=dict(l=20, r=20, t=40, b=20)
    )
    meals_per_day_chart = pio.to_html(fig_meals_bar, full_html=False)

    # Process meals_with_durations
    for x in meals_with_durations:
        x['mealDuration'] = x['mealDuration'] / 60
        x['startTime'] = datetime.strptime(x['startTime'], '%Y-%m-%dT%H:%M:%S.%fZ').strftime('%d %b %Y %I:%M:%S %p')
        x['endTime'] = datetime.strptime(x['endTime'], '%Y-%m-%dT%H:%M:%S.%fZ').strftime('%d %b %Y %I:%M:%S %p')
        x['emissions'] = x['totalKwh'] * 0.4999 * 0.28
        x['energy_cost'] = x['totalKwh'] * 23.0

    fig_metrics_bar = go.Figure(data=[
        go.Scatter(name='Carbon Emissions', x=[date['startTime'] for date in meals_with_durations[::-1]], y=[(e['emissions']*1000) for e in meals_with_durations[::-1]], hovertemplate='Date: %{x}<br>Carbon Emissions: %{y} grams of CO₂', line_shape='spline'),
        go.Scatter(name='Energy Cost', x=[date['startTime'] for date in meals_with_durations[::-1]], y=[e['energy_cost'] for e in meals_with_durations[::-1]], hovertemplate='Date: %{x}<br>Energy Cost: %{y} Kenya Shillings', line_shape='spline'),
        go.Scatter(name='Energy Consumption', x=[date['startTime'] for date in meals_with_durations[::-1]], y=[(e['totalKwh']*1000) for e in meals_with_durations[::-1]], hovertemplate='Date: %{x}<br>Energy: %{y} watt-hours', line_shape='spline')
    ])
    #fig_metrics_bar.update_traces(title='Combined Device Metrics')
    fig_metrics_bar.update_layout(
        xaxis_title='Date',
        yaxis_title='Value',
        showlegend=True,
        autosize=True,
        title_x=0.5,
        height=500,
        margin=dict(l=20, r=20, t=40, b=20),
        #xaxis_visible=False,
        xaxis_showticklabels=False,
        #barmode='group',
        #barcornerradius=10
    )
    metrics_chart = pio.to_html(fig_metrics_bar, full_html=False)

    usr = request.user.username
    if usr == 'John-Maina':
        dat = fetch_data("commandScode")
    else:
        dat = fetch_data("command")
    for z in dat:
        if z["deviceID"] == device_id:
            status = z["active"]
    dat = pd.DataFrame(dat)
    if not dat.empty:
        # Sorting and handling different naming conventions
        def sort_key(x):
            if x == 'OfficeFridge1':
                return float('inf')
            elif x.startswith('device'):
                return int(x.split('device')[-1])
            elif x.startswith('JD-'):
                try:
                    return int(x.split('-')[-1].split('device')[-1])
                except ValueError:
                    return float('inf') - 1
            else:
                return float('inf') - 1
        
        dat['sort_key'] = dat['deviceID'].apply(sort_key)
        dat = dat.sort_values(by='sort_key')

    # Pagination logic
    paginator = Paginator(meals_with_durations, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    dev_List = dat['deviceID'].tolist()

    context = {
        "device_id": str(device_id),  # Ensure device_id is a string
        "runtime": runtime,
        "sum_kwh": sum_kwh,
        "emissions": emissions,
        "meals_with_durations": page_obj,  # Pass paginated meals_with_durations
        "total_meals_per_day": total_meals_per_day,
        "meals_per_day_chart": meals_per_day_chart,
        "metrics_chart": metrics_chart,  # Pass the metrics chart HTML to the template
        "energy_cost": energy_cost,
        "dev_List": dev_List,  # Ensure dev_List is a list of strings
        "status": status,
        "selected_range": str(range_value)
    }

    return render(request, "device_data.html", context)

@login_required
def add_device(request):
    if request.method == 'POST':
        device_name = request.POST.get('device_name')
        if device_name:
            # Replace with your actual endpoint URL
            endpoint = 'https://appliapay.com/addDevice'
            # Replace with your actual credentials
            username = 'admin'
            password = '123Give!@#'
            credentials = (username, password)
            headers = {'Content-Type': 'application/json'}

            data = {'device': device_name}

            response = requests.post(endpoint, json=data, auth=credentials, headers=headers)

            if response.status_code == 200:
                # Redirect to the devices page on success
                return redirect('devices_page')
            else:
                return render(request, 'add_device.html', {'error': 'Failed to add device'})

    return render(request, 'add_device.html')

#################################DOWNLOAD TRANSACTIONS EXCEL##############################################
def export_transactions_excel(request):
    # Fetch data based on the user
    usr = request.user.username
    if usr == 'John-Maina':
        data = fetch_data("mpesarecordsscode")
    else:
        data = fetch_data("mpesarecords")

    # Convert the data to a DataFrame
    df = pd.DataFrame(data)

    # Convert 'transtime' to datetime format
    df['transtime'] = pd.to_datetime(df['transtime'], format='%Y%m%d%H%M%S')

    # Sort the data by 'transtime' in descending order
    df = df.sort_values(by='transtime', ascending=False)

    # Drop the 'time' column to remove it from the export
    df = df.drop(columns=['time'])

    # Create a HttpResponse with content_type as ms-excel
    response = HttpResponse(content_type='application/vnd.ms-excel')
    
    # Specify the file name
    response['Content-Disposition'] = 'attachment; filename="transactions.xlsx"'

    # Use pandas to save the dataframe as an excel file in the response
    df.to_excel(response, index=False, engine='openpyxl')

    return response

#######################AI MIGAA METER DOWNLOAD####################################################
def export_meter_data(request):
    data = fetch_data("migaaMeterDownload")

    # Convert the data to a DataFrame
    df = pd.DataFrame(data)
    # Create a HttpResponse with content_type as ms-excel
    response = HttpResponse(content_type='application/vnd.ms-excel')
    
    # Specify the file name
    response['Content-Disposition'] = 'attachment; filename="migaaMeter.csv"'

    # Use pandas to save the dataframe as an excel file in the response
    df.to_csv(response, index=False)

    return response
