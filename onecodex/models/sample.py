import os
import sys

import requests
from requests.exceptions import HTTPError
from six import string_types

from onecodex.exceptions import OneCodexException
from onecodex.models import OneCodexBase
from onecodex.models.misc import Projects, Tags
from onecodex.models.helpers import truncate_string
from onecodex.lib.upload import upload  # upload_file

class OneCodexBaseCollection(object):
    model = OneCodexBase

    def __init__(self, items, *args, **kwargs):
        self._items = items

    def __iter__(self):
        for x in list.__iter__(self._items):
            yield x

    def append(self, item):
        if not isinstance(item, self.model):
            raise AttributeError
        self._items.append(item)
        

    def extend(self, items):
        if not isinstance(items, self.__class__):
            raise AttributeError
        self._items.extend(items._items)

    def __setitem__(self, index, item):
        if not isinstance(item, self.model):
            raise AttributeError
        self._items[index] = item

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._items[key]
        return self.__class__(self._items[key])  # Slice

    def __len__(self):
        return len(self._items)

    def __repr__(self):
        # FIXME: Special case for 1 item
        return '<{} with {} items [{}...{}]>'.format(self.__class__.__name__, len(self._items), self._items[0].__repr__(), self._items[-1].__repr__())


class Samples(OneCodexBase):
    _resource_path = '/api/v1/samples'

    def __repr__(self):
        return '<{} {}: "{}">'.format(self.__class__.__name__, self.id,
                                      truncate_string(self.filename, 24))

    @classmethod
    def where(cls, *filters, **keyword_filters):
        instances_route = keyword_filters.get('_instances', 'instances')
        limit = keyword_filters.get('limit', None)

        # If there's a filter for project_name, convert that into into a project ID
        projects = None
        project_name = keyword_filters.pop('project_name', None)
        if project_name and 'project' in keyword_filters:
            raise OneCodexException('You cannot query samples by both project and project_name parameters.')

        if project_name:
            projects = Projects.where(name=project_name)
        if projects:
            keyword_filters['project'] = projects[0].id

        # If there's a filter for tag_name, convert that into a list of Tag ID's
        tag_name = keyword_filters.pop('tag_name', None)
        if tag_name and 'tags' in keyword_filters:
            raise OneCodexException('You cannot query samples by both tags and tag_name parameters.')
        if tag_name:
            tags = Tags.where(name=tag_name)
            keyword_filters['tags'] = tags

        # we can only search metadata on our own samples currently
        # FIXME: we need to add `instances_public` and `instances_project` metadata routes to
        # mirror the ones on the samples
        metadata_samples = []
        if instances_route in ['instances']:

            md_schema = next(l for l in Metadata._resource._schema['links']
                             if l['rel'] == instances_route)

            md_where_schema = md_schema['schema']['properties']['where']['properties']
            md_search_keywords = {}
            for keyword in list(keyword_filters):
                # skip out on $uri to prevent duplicate field searches and the others to
                # simplify the checking below
                if keyword in ['$uri', 'sort', '_instances']:
                    continue
                elif keyword in md_where_schema:
                    md_search_keywords[keyword] = keyword_filters.pop(keyword)

            # TODO: should one be able to sort on metadata? here and on the merged list?
            # md_sort_schema = md_schema['schema']['properties']['sort']['properties']
            # # pull out any metadata sort parameters
            # sort = keyword_filters.get('sort', [])
            # if not isinstance(sort, list):
            #     sort = [sort]
            # passthrough_sort = []
            # for keyword in sort:
            #     if keyword in md_sort_schema:
            #         # TODO: set up sort for metadata
            #         pass
            #     else:
            #         passthrough_sort.append(keyword)
            # keyword_filters['sort'] = passthrough_sort

            if len(md_search_keywords) > 0:
                metadata_samples = [md.sample for md in Metadata.where(**md_search_keywords)]

        samples = []
        if len(metadata_samples) == 0:
            samples = super(Samples, cls).where(*filters, **keyword_filters)

        if len(samples) > 0 and len(metadata_samples) > 0:
            # we need to filter samples to just include stuff from metadata_samples
            metadata_sample_ids = {s.id for s in metadata_samples}
            samples = [s for s in samples if s.id in metadata_sample_ids]
        elif len(metadata_samples) > 0:
            # we have to sort the metadata samples manually using the
            # sort parameters for the samples (and then the metadata parameters?)
            # TODO: implement this (see above block)
            samples = metadata_samples

        return SampleCollection(samples[:limit])

    @classmethod
    def search_public(cls, *filters, **keyword_filters):
        keyword_filters['public'] = True
        keyword_filters['limit'] = 100
        return cls.where(*filters, **keyword_filters)

    def save(self):
        """
        Persist changes on this Samples object back to the One Codex server along with any changes
        on its metadata (if it has any).
        """
        super(Samples, self).save()
        if self.metadata is not None:
            self.metadata.save()

    @classmethod
    def upload(cls, filename, threads=None, validate=True):
        """
        Uploads a series of files to the One Codex server. These files are automatically
        validated during upload.

        Parameters
        ----------
        path: list of strings or tuples
            List of full paths to the files. If one (or more) of the list items are a tuple, this
            is parsed as a set of files that are paired and the files are automatically
            iterleaved during upload.
        """
        # TODO: either raise/wrap UploadException or just us the new one in lib.samples
        # upload_file(filename, cls._resource._client.session, None, 100)
        res = cls._resource
        if isinstance(filename, string_types) or isinstance(filename, tuple):
            filename = [filename]
        upload(filename, res._client.session, res, res._client._root_url + '/', threads=threads,
               validate=validate, log_to=sys.stderr)

        # FIXME: pass the auth into this so we can authenticate the callback?
        # FIXME: return a Sample object?

    def download(self, path=None):
        """
        Downloads the original reads file (FASTA/FASTQ) from One Codex.

        Note that this may only work from within a notebook session and the file
        is not guaranteed to exist for all One Codex plan types.

        Parameters
        ----------
        path : string, optional
            Full path to save the file to. If omitted, defaults to the original filename
            in the current working directory.
        """
        if path is None:
            path = os.path.join(os.getcwd(), self.filename)
        try:
            url_data = self._resource.download_uri()
            resp = requests.get(url_data['download_uri'], stream=True)
            # TODO: use tqdm or ProgressBar here to display progress?
            with open(path, 'wb') as f_out:
                for data in resp.iter_content(chunk_size=1024):
                    f_out.write(data)
        except HTTPError as exc:
            if exc.response.status_code == 402:
                raise OneCodexException('You must either have a premium platform account or be in '
                                        'a notebook environment to download samples.')
            else:
                raise OneCodexException('Download failed with an HTTP status code {}.'.format(
                                        exc.response.status_code))


class SampleCollection(OneCodexBaseCollection):
    model = Samples

    def to_otu_table(self, metric='abundance', verbose=False):
        import pandas as pd
        """For a set of samples, return the results as a Pandas DataFrame."""
        assert metric in ['abundance', 'readcount', 'readcount_w_children']
        
        # Keep track of all of the microbial abundances
        dat = {}
        # Keep track of information for each tax_id
        tax_id_info = {}
        
        # Get results for each of the Sample objects that are passed in
        for s in self._items:
            # Get the primary classification for this sample
            a = s._api.Classifications.get(str(s.primary_classification.id))
            
            if a.success is False:
                if verbose:
                    print("Analysis for {} did not succeed, skipping".format(s.filename))
                continue
                
            # Get the results in table format
            result = a.results()['table']
            
            # Record the information (name, parent) for each organism by  its tax ID
            for d in result:
                if d['tax_id'] not in tax_id_info:
                    tax_id_info[d['tax_id']] = {k: d[k] for k in ['name', 'rank', 'parent_tax_id']}

            # Reformat detection infromation as dict of {taxid: value}
            result = {d['tax_id']: d[metric] for d in result if metric in d}

            # Remove entries without the specified metric
            result = {taxid: value for taxid, value in result.items() if value is not None}

            # Remove about 0-values
            result = {taxid: value for taxid, value in result.items() if value > 0}
            
            # Catch any samples that don't have the specified metric
            if len(result) == 0:
                if verbose:
                    print("{} has no entries for {}, skipping.".format(s.filename, metric))
                continue

            # Save the set of microbial abundances
            dat[str(s.id)] = result
        if len(dat) == 0:
            return None

        # Format as a Pandas DataFrame
        df = pd.DataFrame(dat).T.fillna(0)
        
        # Remove columns (tax_ids) with no values that are > 0
        df = df.loc[:, df.sum() > 0]
        
        if verbose:
            print("Returning a data frame with {} samples and {} tax_ids".format(df.shape[0], df.shape[1]))
        return df, tax_id_info


class Metadata(OneCodexBase):
    _resource_path = '/api/v1/metadata'

    def save(self):
        if self.id is None:
            super(Metadata, self).save()  # Create
        else:  # Update
            # Hack: Sample is read and create-only
            # but Potion will try to update since it's not marked
            # readOnly in the schema; we also make sure
            # the linked metadata object is resolved since
            # we auto-save it alongside the sample
            if self._resource._uri and self._resource._status is None:
                assert isinstance(self._resource._properties, dict)

            # Then eject samplea and uri as needed
            ref_props = self._resource._properties
            if 'sample' in ref_props or '$uri' in ref_props:  # May not be there if not resolved!
                ref_props.pop('$uri', None)
                ref_props.pop('sample', None)
                self._resource._update(ref_props)
            else:
                super(Metadata, self).save()
