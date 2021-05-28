from datetime import datetime, time
from urllib.parse import unquote_plus
import boto3
import botocore
import json
import os
import uuid
from PIL import Image, ImageOps
from PIL.ExifTags import TAGS

rds_client = boto3.client('rds-data')
s3_client = boto3.client(
    's3',
    region_name='eu-west-2'
)
events_client = boto3.client('events')
lambda_client = boto3.client('lambda')

bucket = 'peteandrew-photoarchive-eu'
cluster_arn = 'arn:aws:rds:eu-west-2:306578912108:cluster:database-1'
secret_arn = 'arn:aws:secretsmanager:eu-west-2:306578912108:secret:rds-db-credentials/cluster-QBRFG6NNVJEGKYGGMCDHRUGXVA/admin-F2AjV8' 
database = 'photoarchive'
image_longest_sides = {'thumbnail': 300, 'standard': 800}

def add_retry_rule(context):
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
                'Id': 'photos_metadata_processor',
                'Arn': 'arn:aws:lambda:eu-west-2:306578912108:function:photos_metadata_processor',
                'Input': json.dumps({
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
    # Check if RDS DB is available (running)
    # Will raise an exception if not
    rds_client.execute_statement(
        resourceArn = cluster_arn, 
        secretArn = secret_arn, 
        database = database, 
        sql = 'select count(1) from images'
    )

    if 'rule' in event:
        remove_retry_rule(context, event['rule'])

    # Get camera photographers
    response = rds_client.execute_statement(
        resourceArn = cluster_arn, 
        secretArn = secret_arn, 
        database = database, 
        sql = "select camera, photographer from camera_photographer"
    )
    camera_photographers = {}
    for record in response['records']:
        camera = record[0]['stringValue']
        photographer = record[1]['stringValue']
        camera_photographers[camera] = photographer

    # Get 100 rows from image_process_queue
    sql = (
        "select ipq.image_id, i.time_created "
        "from image_process_queue ipq "
        "join images i on i.id = ipq.image_id "
        "limit 100"
    )
    response = rds_client.execute_statement(
        resourceArn = cluster_arn, 
        secretArn = secret_arn, 
        database = database, 
        sql = sql
    )
    for record in response['records']:
        image_id = record[0]['stringValue']
        date_created = record[1]['stringValue']

        year = date_created[:4]
        month = date_created[5:7]
        key = 'originals/{year}/{month}/{id}.jpg'.format(
            year = year,
            month = month,
            id = image_id
        )
        print(key)

        # Get original image file and extract exif data and insert metadata records
        source_path = '/tmp/original_{id}.jpg'.format(id=id)
        s3_client.download_file(bucket, key, source_path)

        with Image.open(source_path) as image:
            exif_data = {}
            for tag, value in image.getexif().items():
                decoded = TAGS.get(tag, tag)
                exif_data[decoded] = value

            print(exif_data)            

            rds_client.execute_statement(
                resourceArn = cluster_arn,
                secretArn = secret_arn,
                database = database,
                sql = 'delete from image_metadata where image_id = :id',
                parameters = [
                    {
                        'name': 'id',
                        'value': {'stringValue': image_id}
                    },
                ]
            )

            try:
                camera = exif_data['Make']
                camera += f" {exif_data['Model']}"
                print(camera)

                rds_client.execute_statement(
                    resourceArn = cluster_arn,
                    secretArn = secret_arn,
                    database = database,
                    sql = 'insert into image_metadata (image_id, type, value) values (:id, "camera", :camera)',
                    parameters = [
                        {
                            'name': 'id',
                            'value': {'stringValue': image_id}
                        },
                        {
                            'name': 'camera',
                            'value': {'stringValue': camera}
                        },
                    ]
                )

                try:
                    photographer = camera_photographers[camera]
                    print(photographer)
                    rds_client.execute_statement(
                        resourceArn = cluster_arn,
                        secretArn = secret_arn,
                        database = database,
                        sql = 'insert into image_metadata (image_id, type, value) values (:id, "photographer", :photographer)',
                        parameters = [
                            {
                                'name': 'id',
                                'value': {'stringValue': image_id}
                            },
                            {
                                'name': 'photographer',
                                'value': {'stringValue': photographer}
                            },
                        ]
                    )

                except KeyError:
                    print("No photographer for camera")

            except KeyError:
                print("No camera data")


            # Check whether thumbnail exists and if not, generate one
            thumbnail_key = 'thumbnails/{year}/{month}/{id}.jpg'.format(
                year = year,
                month = month,
                id = image_id
            )
            try:
                s3_client.head_object(Bucket=bucket, Key=thumbnail_key)
            except botocore.exceptions.ClientError as e:
                target_path = '/tmp/resized_{id}.jpg'.format(id=id)
                new_image = resize(image, 'thumbnail')
                new_image.save(target_path)

                s3_client.upload_file(
                    target_path,
                    bucket,
                    thumbnail_key,
                    ExtraArgs={'ContentType': 'image/jpeg'}
                )

                os.remove(target_path)

        os.remove(source_path)

        rds_client.execute_statement(
            resourceArn = cluster_arn, 
            secretArn = secret_arn, 
            database = database, 
            sql = "delete from image_process_queue where image_id = :image_id",
            parameters = [
                {
                    'name': 'image_id',
                    'value': {'stringValue': image_id}
                }
            ]
        )

    # Get count of photos remaining to be processed
    response = rds_client.execute_statement(
        resourceArn = cluster_arn, 
        secretArn = secret_arn, 
        database = database, 
        sql = "select count(1) from image_process_queue"
    )
    remaining_images = response['records'][0][0]['longValue']
    print(f'Images remaining: {remaining_images}')

    if remaining_images > 0:
        add_retry_rule(context)