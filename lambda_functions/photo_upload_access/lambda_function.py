import json
import boto3
from botocore.client import Config

bucket = 'peteandrew-photoarchive-eu'

s3_client = boto3.client(
    's3',
    region_name='eu-west-2',
    config=Config(signature_version='s3v4')
)


def lambda_handler(event, context):
    filename = event['queryStringParameters']['filename']
    image_key = 'uploads/{filename}'.format(
        filename = filename,
    )
    url = s3_client.generate_presigned_url(
        ClientMethod='put_object',
        Params={
            'Bucket': bucket,
            'Key': image_key,
            'ContentType': 'image/jpeg',
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
