from datetime import datetime, time
from urllib.parse import unquote_plus
import boto3
import botocore
import json
import uuid
from PIL import Image
from PIL.ExifTags import TAGS

events_client = boto3.client('events')
lambda_client = boto3.client('lambda')
rds_client = boto3.client('rds-data')
s3_client = boto3.client(
    's3',
    region_name='eu-west-2'
)

cluster_arn = 'arn:aws:rds:eu-west-2:306578912108:cluster:database-1'
secret_arn = 'arn:aws:secretsmanager:eu-west-2:306578912108:secret:rds-db-credentials/cluster-QBRFG6NNVJEGKYGGMCDHRUGXVA/admin-F2AjV8' 
database = 'photoarchive'

def add_retry_rule(context, s3_records):
    """
    Create a Cloudwatch rule to retry this function
    after 1 minute
    """
    now = datetime.now()
    rule_name = 'retry-{timestamp}'.format(
        timestamp=now.strftime("%s")
    )
    response = events_client.put_rule(
        Name=rule_name,
        ScheduleExpression='rate(1 minute)',
        State='ENABLED',
    )
    rule_arn = response['RuleArn']
    events_client.put_targets(
        Rule=rule_name,
        Targets=[
            {
                'Id': 'photo_upload_processor',
                'Arn': 'arn:aws:lambda:us-east-1:306578912108:function:photo_upload_processor',
                'Input': json.dumps({
                    'Records': s3_records,
                    'rule': rule_name,
                })
            }
        ]
    )
    lambda_client.add_permission(
        FunctionName=context.invoked_function_arn,
        StatementId=rule_name,
        Action='lambda:InvokeFunction',
        Principal='events.amazonaws.com',
        SourceArn=rule_arn,
    )
    print("Retry rule added: {rule_name}".format(rule_name=rule_name))

def remove_retry_rule(context, rule):
    """
    Remove existing Cloudwatch event rule this function
    was called from
    """
    response = events_client.list_targets_by_rule(
        Rule=rule
    )
    target_ids = [target['Id'] for target in response['Targets']]
    events_client.remove_targets(
        Rule=rule,
        Ids=target_ids
    )
    events_client.delete_rule(
        Name=rule
    )
    lambda_client.remove_permission(
        FunctionName=context.invoked_function_arn,
        StatementId=rule
    )
    print("Retry rule removed: {rule}".format(rule=rule))

def lambda_handler(event, context):
    # Validity check s3 records exist
    if 'Records' not in event:
        return
    s3_records = event['Records']
    if len(s3_records) == 0:
        return

    # Check if RDS DB is available (running)
    try:
        rds_client.execute_statement(
            resourceArn = cluster_arn, 
            secretArn = secret_arn, 
            database = database, 
            sql = 'select count(1) from images'
        )
    except botocore.errorfactory.BadRequestException:
        # DB not running, set up retry rule if one does not already exist
        print("DB not running")
        if 'rule' not in event:
            add_retry_rule(context, s3_records)

    # DB is available, remove retry rule if it exists
    if 'rule' in event:
        remove_retry_rule(context, event['rule'])

    for record in s3_records:
        bucket = record['s3']['bucket']['name']
        print(bucket)
        key = unquote_plus(record['s3']['object']['key'])
        print(key)
        image_id = str(uuid.uuid4())
        tmp_path = '/tmp/{image_id}.jpg'.format(image_id=image_id)
        s3_client.download_file(bucket, key, tmp_path)

        with Image.open(tmp_path) as image:
            exif_data = {}
            for tag, value in image.getexif().items():
                decoded = TAGS.get(tag, tag)
                exif_data[decoded] = value

            print(exif_data)

            try:
                date_time = exif_data['DateTime']
                year = date_time[:4]
                month = date_time[5:7]
                time_created = year + '-' + month + '-' + date_time[8:]
            except KeyError:
                print('no DateTime')
                year = '1970'
                month = '01'
                time_created = '1970-01-01'

            time_processed = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

            rds_client.execute_statement(
                resourceArn = cluster_arn, 
                secretArn = secret_arn, 
                database = database, 
                sql = 'insert into images (id, time_created, time_processed) values (:id, :time_created, :time_processed)',
                parameters = [
                    {
                        'name': 'id',
                        'value': {'stringValue': image_id}
                    },
                    {
                        'name': 'time_created',
                        'value': {'stringValue': time_created}
                    },
                    {
                        'name': 'time_processed',
                        'value': {'stringValue': time_processed}
                    }
                ]
            )

            target_key = 'originals/{year}/{month}/{id}.jpg'.format(
                year = year,
                month = month,
                id = image_id
            )
            s3_client.copy_object(
                Bucket=bucket,
                CopySource={
                    'Bucket': bucket,
                    'Key': key
                },
                Key=target_key
            )
            s3_client.delete_object(
                Bucket=bucket,
                Key=key,
            )

        