# System
import mimetypes
import errno
from io import BytesIO
from base64 import b64decode

# Packages
from django.http import HttpResponse, Http404
from django.conf import settings
from pilbox.errors import PilboxError
from swiftclient.exceptions import ClientException as SwiftClientException
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import ParseError

# Local
from lib.processors import image_processor
from lib.http_helpers import error_response
from lib.file_helpers import create_asset
from auth import token_authorization


class Asset(APIView):
    """
    Actions on a single asset respource.
    """

    base_name = 'asset'

    def get(self, request, file_path):
        """
        Get a single asset, 404ing if we get an OSError.
        """

        mimetype = mimetypes.guess_type(file_path)[0]

        try:
            asset_stream = BytesIO(settings.FILE_MANAGER.fetch(file_path))
        except SwiftClientException as error:
            return error_response(error, file_path)

        image_types = ["image/png", "image/jpeg"]

        # Run images through processor
        if request.GET and mimetype in image_types:
            try:
                asset_stream = image_processor(
                    asset_stream,
                    request.GET
                )
            except PilboxError as error:
                return error_response(error, file_path)

        # Return asset
        return HttpResponse(asset_stream.read(), mimetype)

    @token_authorization
    def delete(self, request, file_path):
        """
        Delete a single named asset, 204 if successful
        """

        try:
            settings.DATA_MANAGER.delete(file_path)
            settings.FILE_MANAGER.delete(file_path)
            return Response({"message": "Deleted {0}".format(file_path)})

        except SwiftClientException as err:
            return error_response(err, file_path)

    @token_authorization
    def put(self, request, file_path):
        """
        Update metadata against an asset
        """

        tags = request.DATA.get('tags', '')

        data = settings.DATA_MANAGER.update(file_path, tags)

        return Response(data)


class AssetList(APIView):
    """
    Actions on the asset collection.
    """

    base_name = 'asset_list'

    @token_authorization
    def get(self, request):
        """
        Get all assets.

        Filter asset by providing a query
        /?q=<query>

        Query parts should be space separated,
        and results will match all parts

        Currently, the query will only be matched against
        file paths
        """

        queries = request.GET.get('q', '').split(' ')

        regex_string = '({0})'.format('|'.join(queries))

        return Response(settings.DATA_MANAGER.find(regex_string))

    @token_authorization
    def post(self, request):
        """
        Create a new asset
        """

        tags = request.DATA.get('tags', '')
        asset = request.DATA.get('asset')
        friendly_name = request.DATA.get('friendly-name')
        url_path = request.DATA.get('url-path', '').strip('/')

        try:
            url_path = create_asset(
                file_data=b64decode(asset),
                friendly_name=friendly_name,
                tags=tags,
                url_path=url_path
            )
        except IOError as create_error:
            if create_error.errno == errno.EEXIST:
                return error_response(create_error)
            else:
                raise create_error
        except SwiftClientException as swift_error:
            return error_response(swift_error, url_path)

        # Return the list of data for the created files
        import ipdb; ipdb.set_trace()
        return Response(settings.DATA_MANAGER.fetch_one(url_path), 201)


class AssetJson(APIView):
    """
    Data about an asset
    """

    base_name = 'asset_json'

    @token_authorization
    def get(self, request, file_path):
        """
        Get data for an asset by path
        """

        if settings.DATA_MANAGER.exists(file_path):
            response = Response(settings.DATA_MANAGER.fetch_one(file_path))
        else:
            asset_error = file_error(
                error_number=errno.ENOENT,
                message="No JSON data found for file {0}".format(file_path),
                filename=file_path
            )
            response = error_response(asset_error)

        return response


class Tokens(APIView):
    """
    HTTP methods for managing the collection of authentication tokens
    """

    @token_authorization
    def get(self, request):
        """
        Get data for an asset by path
        """

        return Response(settings.TOKEN_MANAGER.all())

    @token_authorization
    def post(self, request):
        """
        Update metadata against an asset
        """

        name = request.DATA.get('name')
        body = {'name': name}
        token = False

        if not name:
            raise ParseError('To create a token, please specify a name')

        elif settings.TOKEN_MANAGER.exists(name):
            raise ParseError('Another token by that name already exists')

        else:
            token = settings.TOKEN_MANAGER.create(name)

            if token:
                body['message'] = 'Token created'
                body['token'] = token['token']
            else:
                raise ParseError('Failed to create a token')

        return Response(body)


class Token(APIView):
    """
    HTTP methods for managing a single authentication token
    """

    @token_authorization
    def get(self, request, name):
        """
        Get token data by name
        """

        token = settings.TOKEN_MANAGER.fetch(name)

        if not token:
            raise Http404

        return Response(token)

    @token_authorization
    def delete(self, request, name):
        """
        Delete a single named authentication token, 204 if successful
        """

        status = 200

        body = settings.TOKEN_MANAGER.delete(name) or {}

        if body:
            body['message'] = "Successfully deleted."
        else:
            raise Http404

        return Response(body, status)
