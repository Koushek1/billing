import boto3
import json
import datetime
import os
import traceback
from dateutil.relativedelta import relativedelta

# Conversion rate (1 USD = X INR)
USD_TO_INR_RATE = 83  # Update with current rate if necessary

def get_cost_and_usage(client, start_date_str, end_date_str):
    """
    Fetch cost and usage data from AWS Cost Explorer with account grouping
    """
    try:
        return client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date_str,
                'End': end_date_str
            },
            Granularity='MONTHLY',
            Metrics=['UnblendedCost'],
            GroupBy=[
                {'Type': 'DIMENSION', 'Key': 'LINKED_ACCOUNT'}
            ]
        )
    except Exception as e:
        print(f"Error fetching cost and usage data: {str(e)}")
        raise

def process_billing_data(response):
    """
    Process the Cost Explorer response into formatted billing data
    """
    billing_data = []
    sl_no = 1
    
    try:
        for result in response['ResultsByTime']:
            month_period = datetime.datetime.strptime(
                result['TimePeriod']['Start'], '%Y-%m-%d'
            ).strftime('%B %Y')
            
            for group in result.get('Groups', []):
                account_number = group['Keys'][0]
                cost_usd = float(group['Metrics']['UnblendedCost']['Amount'])
                cost_inr = round(cost_usd * USD_TO_INR_RATE, 2)
                
                billing_data.append({
                    'sl_no': sl_no,
                    'account_number': account_number,
                    'month_period': month_period,
                    'cost_usd': cost_usd,
                    'cost_inr': cost_inr
                })
                sl_no += 1
                
        return billing_data
    except Exception as e:
        print(f"Error processing billing data: {str(e)}")
        raise

def generate_table_rows(billing_data):
    """
    Generate HTML table rows from billing data
    """
    try:
        rows = ""
        for entry in billing_data:
            rows += f"""
            <tr>
                <td>{entry['sl_no']}</td>
                <td>{entry['account_number']}</td>
                <td>{entry['month_period']}</td>
                <td>${entry['cost_usd']:.2f}</td>
                <td>₹{entry['cost_inr']:.2f}</td>
            </tr>
            """
        return rows
    except Exception as e:
        print(f"Error generating table rows: {str(e)}")
        raise

def get_html_template_from_s3(s3_client, bucket_name, object_key):
    """
    Fetch the HTML template from S3
    """
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        return response['Body'].read().decode('utf-8')
    except Exception as e:
        print(f"Error fetching HTML template from S3: {str(e)}")
        raise

def handler(event, context):
    """
    Lambda handler function
    """
    try:
        # Initialize AWS clients
        ce_client = boto3.client('ce')
        s3_client = boto3.client('s3')
        
        # Get S3 bucket name from environment variables
        bucket_name = os.environ.get('S3_BUCKET', 'aws-billing-dashboard-4frfdktl')
        object_key = 'index.html'
        
        # Fetch HTML template
        html_template = get_html_template_from_s3(s3_client, bucket_name, object_key)
        
        # Calculate date range (first day of last 12 months to first day of current month)
        end_date = (datetime.datetime.now() + relativedelta(months=1)).replace(day=1)
        start_date = end_date - relativedelta(months=12)
        
        # Format dates for AWS Cost Explorer
        start_date_str = start_date.strftime('%Y-%m-01')
        end_date_str = end_date.strftime('%Y-%m-01')
        
        # Get cost and usage data
        print(f"Fetching cost data from {start_date_str} to {end_date_str}")
        response = get_cost_and_usage(ce_client, start_date_str, end_date_str)
        
        # Process billing data and generate table
        billing_data = process_billing_data(response)
        table_rows = generate_table_rows(billing_data)
        
        # Calculate totals
        total_usd = sum(entry['cost_usd'] for entry in billing_data)
        total_inr = sum(entry['cost_inr'] for entry in billing_data)
        
        # Update HTML template
        html_output = html_template.replace('{{tableRows}}', table_rows)
        html_output = html_output.replace('{{totalCostUSD}}', f"${total_usd:.2f}")
        html_output = html_output.replace('{{totalCostINR}}', f"₹{total_inr:.2f}")
        
        # Return success response
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'text/html',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'no-cache'
            },
            'body': html_output
        }
        
    except Exception as e:
        print(f"Error in lambda function: {str(e)}")
        print(traceback.format_exc())
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal Server Error',
                'details': str(e),
                'trace': traceback.format_exc()
            })
        }
