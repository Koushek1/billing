import boto3
import json
import datetime
import os
import traceback
from dateutil.relativedelta import relativedelta

def get_cost_and_usage(client, start_date_str, end_date_str):
    """
    Fetch cost and usage data from AWS Cost Explorer
    """
    return client.get_cost_and_usage(
        TimePeriod={
            'Start': start_date_str,
            'End': end_date_str
        },
        Granularity='MONTHLY',
        Metrics=['UnblendedCost'],
        GroupBy=[
            {'Type': 'DIMENSION', 'Key': 'SERVICE'}
        ]
    )

def process_billing_data(response):
    """
    Process the Cost Explorer response into a more usable format
    """
    billing_data = []
    total_cost = 0
    
    for result in response['ResultsByTime']:
        month_data = {
            'period': result['TimePeriod']['Start'],
            'services': [],
            'total_cost': 0
        }
        
        for group in result['Groups']:
            service_name = group['Keys'][0]
            cost = float(group['Metrics']['UnblendedCost']['Amount'])
            
            month_data['services'].append({
                'service': service_name,
                'cost': round(cost, 2)
            })
            month_data['total_cost'] += cost
            total_cost += cost
        
        month_data['total_cost'] = round(month_data['total_cost'], 2)
        billing_data.append(month_data)
    
    return billing_data, round(total_cost, 2)

def handler(event, context):
    try:
        # Create Cost Explorer client
        client = boto3.client('ce')
        
        # Calculate date range for last 12 months
        end_date = datetime.datetime.now()
        start_date = end_date - relativedelta(months=12)
        
        # Format dates for AWS Cost Explorer
        start_date_str = start_date.strftime('%Y-%m-01')
        end_date_str = end_date.strftime('%Y-%m-01')
        
        try:
            # Get cost and usage data
            response = get_cost_and_usage(client, start_date_str, end_date_str)
        except Exception as ce_error:
            print(f"Cost Explorer Error: {str(ce_error)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Cost Explorer Error',
                    'details': str(ce_error)
                })
            }
        
        # Process the billing data
        billing_data, total_cost = process_billing_data(response)
        
        # Add summary information
        result = {
            'billing_data': billing_data,
            'summary': {
                'total_cost': total_cost,
                'start_date': start_date_str,
                'end_date': end_date_str
            }
        }
        
        # Try to upload to S3
        try:
            s3 = boto3.client('s3')
            s3.put_object(
                Bucket=os.environ['S3_BUCKET'],
                Key='billing-data.json',
                Body=json.dumps(result),
                ContentType='application/json',
                ACL='public-read'
            )
        except Exception as s3_error:
            print(f"S3 upload failed: {str(s3_error)}")
            # Continue even if S3 upload fails
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'no-cache'
            },
            'body': json.dumps(result)
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