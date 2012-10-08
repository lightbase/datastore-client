#!/usr/bin/env python
'''Library and command line client for the CKAN Datastore (written in Python).

For command line usage do::

    ./datastore/client.py -h

Note that CKAN DataStore is, in essence, ElasticSearch so you can use any
ElasticSearch client (http://www.elasticsearch.org/guide/appendix/clients.html)
to interact with it.
'''
import urlparse
import mimetypes
import os
import ConfigParser
import urllib2
import json
import csv
import time
import logging
import ast

logger = logging.getLogger('datastore.client')


class DataStoreClient:
    def __init__(self, url):
        url = url.rstrip('/')
        self.parsed = urlparse.urlparse(url)
        newparsed = list(self.parsed)
        username = self.parsed.username
        self.netloc = self.parsed.netloc
        if username:
            # get rid of username:password@ in netloc
            self.netloc = self.parsed.netloc.split('@')[1]
            newparsed[1] = self.netloc
        self.url = urlparse.urlunparse(newparsed)
        # elastic search type name
        self.es_type_name = self.parsed.path.split('/')[-1] 
        self.es_indice_name = self.parsed.path.split('/')[-1] 
        self._setup_authorization(username)

    def query(self, query):
        '''Perform a query on ElasticSearch endpoint.
        
        :param query: a dictionary specifying the elasticsearch query as per
        elastic search spec.
        '''
        url = self.url + '/_search'
        q = json.dumps(query)
        req = urllib2.Request(url, q, self._headers)
        out = urllib2.urlopen(req).read()
        return json.loads(out)

    def upsert(self, dict_iterator):
        '''Insert / update documents provided in dict_iterator.'''
        start = time.time()
        url = self.url + '/_bulk'

        def send_request(data):
            post_data = "%s%s" % ("\n".join(data), "\n")
            req = urllib2.Request(url, post_data, self._headers)
            return urllib2.urlopen(req)

        data = []
        for count,dict_ in enumerate(dict_iterator):
            # data.append(json.dumps({"index": {"_id": count+1}}))

            bulkmeta = {"index": {}}
            # Eduardo: 2012-09-05
            # Enumerator returns dict as string. We have to convert so it works
            dict_ = ast.literal_eval(dict_)
            
            if 'id' in dict_: 
                bulkmeta['index']['_id'] = dict_['id']
            
            data.append(json.dumps(bulkmeta))
            data.append(json.dumps(dict_))
            if (count % 100) == 0:
                response = send_request(data)
                data[:] = []
                logger.debug('%s %s' % (count, (time.time() - start)))
        if data:
            send_request(data)
            logger.debug('%s %s' % (count, (time.time() - start)))

    def upload(self, filepath_or_fileobj, filetype=None):
        '''Upload data to webstore table. Additional required arguments is file path
        with data to upload and optional {filetype} giving type of file.
        '''
        fileobj = filepath_or_fileobj
        if isinstance(filepath_or_fileobj, basestring):
            if not filetype:
                filetype = mimetypes.guess_type(filepath_or_fileobj)[0]
            fileobj = open(filepath_or_fileobj)
        if filetype.endswith('csv'):
            self.upsert(csv.DictReader(fileobj))
        elif filetype.endswith('json'):
            self.upsert(json.load(fileobj))
        else: 
            raise ValueError('Unsupported format: %s' % filetype)

    def delete(self):
        '''Delete this DataStore table.'''
        opener = urllib2.build_opener(urllib2.HTTPHandler)
        request = urllib2.Request(self.url)
        if self.authorization:
            request.add_header('Authorization', self.authorization)
        request.get_method = lambda: 'DELETE'
        response = opener.open(request)
        return response.read()

    def mapping(self):
        '''Get the mapping for this DataStore table.'''
        url = self.url + '/_mapping'
        req = urllib2.Request(url, None, self._headers)
        data = urllib2.urlopen(req).read()
        data = json.loads(data)
        return data

    def mapping_update(self, mapping):
        '''Update the mapping for this DataStore table.
        
        @param mapping: mapping dict for this type as per
        http://www.elasticsearch.org/guide/reference/api/admin-indices-put-mapping.html

        Note that you need not (and should not) include the type name, i.e. we
        will PUT to mapping API:

        {type-name}: {mapping}
        '''
        url = self.url + '/_mapping'
        data = json.dumps({self.es_type_name: mapping})
        try:
            out = self._request(url, data, 'PUT')
        except Exception, inst:
            logger.error('%s: %s' % (inst.url, inst.read()))
            raise
        logger.debug('%s: %s' % (url, out))
        return out

    def settings(self):
        '''Update settings for this index.'''
        url = self.url + '/_settings'
        req = urllib2.Request(url, None, self._headers)
        data = urllib2.urlopen(req).read()
        data = json.loads(data)
        return data

    def settings_update(self, settings):
        '''Update the settings for this DataStore indice.
        
        @param settings: settings dict for this type as per
		http://www.elasticsearch.org/guide/reference/api/admin-indices-create-index.html

        Note that you need not (and should not) include the indice name, i.e. we
        will PUT to settings API:

        {indice}: {settings}
        '''
        # Close index first
        url_close = self.url + '/_close'
        try:
            out = self._request(url_close, {}, 'POST')
        except Exception, inst:
            logger.error('%s: %s' % (inst.url, inst.read()))
            raise
        logger.debug('%s: %s' % (url_close, out))

        url = self.url + '/_settings'
        data = json.dumps(settings)
        try:
            out = self._request(url, data, 'PUT')
        except Exception, inst:
            logger.error('%s: %s' % (inst.url, inst.read()))
            raise
        logger.debug('%s: %s' % (url, out))

        # Now open index
        url_open = self.url + '/_open'
        try:
            out = self._request(url_open, {}, 'POST')
        except Exception, inst:
            logger.error('%s: %s' % (inst.url, inst.read()))
            raise
        logger.debug('%s: %s' % (url_open, out))

        return out

    def index_create(self, settings):
        '''Update the settings for this DataStore indice.
        
        @param settings: settings dict for this type as per
		http://www.elasticsearch.org/guide/reference/api/admin-indices-create-index.html

        Note that you need not (and should not) include the indice name, i.e. we
        will PUT to settings API:

        {indice}: {settings}
        '''
        url = self.url
        data = json.dumps(settings)
        try:
            out = self._request(url, data, 'PUT')
        except Exception, inst:
            logger.error('%s: %s' % (inst.url, inst.read()))
            raise
        logger.debug('%s: %s' % (url, out))
        return out

    def _request(self, url, data, method):
        opener = urllib2.build_opener(urllib2.HTTPHandler)
        request = urllib2.Request(url, data, self._headers)
        request.get_method = lambda: method
        response = opener.open(request)
        return response.read()

    def _setup_authorization(self, username, password=None):
        '''Get authorization field for authorization header.
        
        If password is None we assume username is in fact API key.
        '''
        if username and password:
            secret = username + ':' + password
            self.authorization = 'Basic ' + secret.encode('base64')
        elif username: # API key
            self.authorization = username
        else:
            self.authorization = self._get_api_key_from_config()
        self._headers = {}
        if self.authorization:
            self._headers['Authorization'] = self.authorization

    def _get_api_key_from_config(self):
        config_path = os.path.join(os.path.expanduser('~'), '.dpmrc')
        if os.path.exists(config_path):
            cfgparser = ConfigParser.SafeConfigParser()
            cfgparser.readfp(open(config_path))
            section = 'index:%s' % self.netloc
            if cfgparser.has_section(section):
                api_key = cfgparser.get(section, 'api_key', '')
                return api_key

class TestItOut:
    base_url = 'http://localhost:9200/api/data'

    def test_url_parse(self):
        url = 'http://abc@localhost/api/data/75328a3a-e566-4993-9115-6e915ed7362c'
        client = DataStoreClient(url)
        assert client.netloc == 'localhost'
        assert client.authorization == 'abc'
        assert client.es_type_name == '75328a3a-e566-4993-9115-6e915ed7362c' 

    def test_delete(self):
        url = self.base_url + '/delete-test'
        client = DataStoreClient(url)
        out = client.delete()
        data = json.loads(out)
        assert data['ok'] == True, data

    def test_upload(self):
        url = self.base_url + '/update-test'
        from StringIO import StringIO
        data = StringIO("""[{"a": 1, "b": 2, "c": 3}]""")
        client = DataStoreClient(url)
        client.upload(data, filetype='json')

    def test_query(self):
        url = self.base_url + '/update-test'
        data = [
            {"a": 1, "b": 2, "c": "UK"},
            {"a": 2, "b": 5, "c": "UK"},
            {"a": 2, "b": 5, "c": "DE"}
        ]
        client = DataStoreClient(url)
        client.upsert(data)
        query = {
            'query': { 
                'match_all': {}
            }
        }
        out = client.query(query)
        assert out['hits']['total']

    def test_mapping(self):
        url = self.base_url + '/mapping-test'
        client = DataStoreClient(url)
        client.delete()
        mapping = {
            'properties': {
                'url': {
                    'type': 'string'
                }
            }
        }
        client.mapping_update(mapping)
        out = client.mapping()
        url = out['mapping-test']['properties']['url']
        assert url
        assert url['type'] == 'string', url


## ======================================
## Command line interface

import sys
import inspect
import optparse
def _object_methods(obj):
    methods = inspect.getmembers(obj, inspect.ismethod)
    methods = filter(lambda (name,y): not name.startswith('_'), methods)
    methods = dict(methods)
    return methods

def _main(functions_or_object, option_list=None):
    isobject = inspect.isclass(functions_or_object)
    if isobject:
        _methods = _object_methods(functions_or_object)
    else:
        _methods = _module_functions(functions_or_object)

    usage = '''%prog {action} {table-url} [additional-arguments]

table-url is CKAN resource or webstore table url

Actions:
    '''
    usage += '\n    '.join(
        [ '%s: %s' % (name, m.__doc__ if m.__doc__ else '') for (name,m)
        in sorted(_methods.items()) ])
    parser = optparse.OptionParser(usage, option_list=option_list)
    options, args = parser.parse_args()

    if not len(args) >= 2 or not args[0] in _methods:
        parser.print_help()
        sys.exit(1)

    method = args[0]
    url = args[1]
    optdict = options.__dict__
    if isobject:
        getattr(functions_or_object(url), method)(*args[2:], **optdict)
    else:
        _methods[method](*args[1:], **optdict)

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    _main(DataStoreClient)

