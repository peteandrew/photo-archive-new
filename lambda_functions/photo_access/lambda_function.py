import json
import boto3
import botocore
from botocore.client import Config
from PIL import Image, ImageOps

bucket = 'peteandrew-photoarchive-eu'
image_longest_sides = {'thumbnail': 500, 'standard': 2000}

s3_client = boto3.client(
    's3',
    region_name='eu-west-2',
    config=Config(signature_version='s3v4')
)

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
    id = event['queryStringParameters']['id']
    year = event['queryStringParameters']['year']
    month = event['queryStringParameters']['month']
    image_type = event['queryStringParameters']['image_type']
    if image_type not in ('thumbnail', 'standard'):
        image_type = 'thumbnail'

    folder = 'thumbnails' if image_type == 'thumbnail' else 'standard'
    image_key = '{folder}/{year}/{month}/{id}.jpg'.format(
        folder = folder,
        year = year,
        month = month,
        id = id
    )
    try:
        s3_client.head_object(Bucket=bucket, Key=image_key)
    except botocore.exceptions.ClientError as e:
        source_key = 'originals/{year}/{month}/{id}.jpg'.format(
            year = year,
            month = month,
            id = id
        )
        source_path = '/tmp/original_{id}.jpg'.format(id=id)
        target_path = '/tmp/resized_{id}.jpg'.format(id=id)
        s3_client.download_file(bucket, source_key, source_path)

        with Image.open(source_path) as image:
            new_image = resize(image, image_type)
            new_image.save(target_path)

        s3_client.upload_file(
            target_path,
            bucket,
            image_key,
            ExtraArgs={'ContentType': 'image/jpeg'}
        )

    url = s3_client.generate_presigned_url(
        ClientMethod='get_object',
        Params={
            'Bucket': bucket,
            'Key': image_key
        },
        ExpiresIn=600
    )

    return {
        'statusCode': 200,
        'headers': {
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
        },
        'body': json.dumps({'url': url})
    }
