from datetime import datetime, time
from urllib.parse import unquote_plus
import boto3
import json
import uuid
from PIL import Image, ImageOps
from PIL.ExifTags import TAGS

rds_client = boto3.client('rds-data')
s3_client = boto3.client(
    's3',
    region_name='eu-west-2'
)

cluster_arn = 'arn:aws:rds:eu-west-2:306578912108:cluster:database-1'
secret_arn = 'arn:aws:secretsmanager:eu-west-2:306578912108:secret:rds-db-credentials/cluster-QBRFG6NNVJEGKYGGMCDHRUGXVA/admin-F2AjV8' 
database = 'photoarchive'
image_longest_sides = {'thumbnail': 300, 'standard': 800}

def resize(image, image_type):
    new_longest_side = image_longest_sides[image_type]

    if image.size[0] > image.size[1]:
        width_longest = True
        cur_longest_side = image.size[0]
    else:
        width_longest = False
        cur_longest_side = image.size[1]

    # If the current longest side is less than or equal to the new longest side
    # then we don't need to do any resizing, return current size
    if cur_longest_side <= new_longest_side:
        new_size = image.size
    else:
        ratio = image.size[1] / image.size[0]

        if width_longest:
            new_size = (new_longest_side, round(new_longest_side * ratio))
        else:
            new_size = (round(new_longest_side / ratio), new_longest_side)

    return ImageOps.exif_transpose(image.resize(new_size, Image.BICUBIC))

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

            try:
                camera = exif_data['Make']
                camera += f" {exif_data['Model']}"
                camera_tag = f"camera: {camera}"
                rds_client.execute_statement(
                    resourceArn = cluster_arn,
                    secretArn = secret_arn,
                    database = database,
                    sql = 'insert into image_tag (image_id, tag) values (:id, :tag)',
                    parameters = [
                        {
                            'name': 'id',
                            'value': {'stringValue': image_id}
                        },
                        {
                            'name': 'tag',
                            'value': {'stringValue': camera_tag}
                        },
                    ]
                )

            except KeyError:
                pass

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

            for image_type in ['thumbnail', 'standard']:
                target_path = '/tmp/resized_{id}.jpg'.format(id=image_id)
                new_image = resize(image, image_type)
                new_image.save(target_path)
                folder = 'thumbnails' if image_type == 'thumbnail' else 'standard'
                target_key = '{folder}/{year}/{month}/{id}.jpg'.format(
                    folder = folder,
                    year = year,
                    month = month,
                    id = image_id
                )
                s3_client.upload_file(
                    target_path,
                    bucket,
                    target_key,
                    ExtraArgs={'ContentType': 'image/jpeg'}
                )
        