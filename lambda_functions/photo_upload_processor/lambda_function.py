from datetime import datetime, time
from urllib.parse import unquote_plus
import boto3
import json
import uuid
from PIL import Image
from PIL.ExifTags import TAGS

rds_client = boto3.client('rds-data')
s3_client = boto3.client(
    's3',
    region_name='eu-west-2'
)

cluster_arn = 'arn:aws:rds:eu-west-2:306578912108:cluster:database-1'
secret_arn = 'arn:aws:secretsmanager:eu-west-2:306578912108:secret:rds-db-credentials/cluster-QBRFG6NNVJEGKYGGMCDHRUGXVA/admin-F2AjV8' 
database = 'photoarchive'

def lambda_handler(event, context):
    # Validity check s3 records exist
    if 'Records' not in event:
        return
    s3_records = event['Records']
    if len(s3_records) == 0:
        return

    # Check if RDS DB is available (running)
    # Will raise an exception if not and function will be retried
    rds_client.execute_statement(
        resourceArn = cluster_arn, 
        secretArn = secret_arn, 
        database = database, 
        sql = 'select count(1) from images'
    )

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

        