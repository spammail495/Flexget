import re
import urllib
import logging
from plugin_urlrewriting import UrlRewritingError
from flexget.entry import Entry
from flexget.plugin import register_plugin, internet, PluginWarning
from flexget.utils import requests
from flexget.utils.soup import get_soup
from flexget.utils.search import torrent_availability, StringComparator
from flexget import validator

log = logging.getLogger('piratebay')

CATEGORIES = {
    'all': 0,
    'audio': 100,
    'music': 101,
    'video': 200,
    'movies': 201,
    'tv': 205,
    'highres movies': 207,
    'comics': 602
}

SORT = {
    'default': 99, # This is piratebay default, not flexget default.
    'date': 3,
    'size': 5,
    'seeds': 7,
    'leechers': 9
}

class UrlRewritePirateBay(object):
    """PirateBay urlrewriter."""

    def validator(self):
        root = validator.factory()
        root.accept('boolean')
        advanced = root.accept('dict')
        advanced.accept('choice', key='category').accept_choices(CATEGORIES)
        advanced.accept('integer', key='category')
        advanced.accept('choice', key='sort_by').accept_choices(SORT)
        advanced.accept('boolean', key='sort_reverse')
        return root

    # urlrewriter API
    def url_rewritable(self, task, entry):
        url = entry['url']
        if url.endswith('.torrent'):
            return False
        url = url.replace('thepiratebay.org', 'thepiratebay.se')
        if url.startswith('http://thepiratebay.se/'):
            return True
        if url.startswith('http://torrents.thepiratebay.se/'):
            return True
        return False

    # urlrewriter API
    def url_rewrite(self, task, entry):
        if not 'url' in entry:
            log.error("Didn't actually get a URL...")
        else:
            log.debug("Got the URL: %s" % entry['url'])
        if entry['url'].startswith(('http://thepiratebay.se/search/', 'http://thepiratebay.org/search/')):
            # use search
            try:
                entry['url'] = self.search(entry['title'])[0]['url']
            except PluginWarning, e:
                raise UrlRewritingError(e)
        else:
            # parse download page
            entry['url'] = self.parse_download_page(entry['url'])

    @internet(log)
    def parse_download_page(self, url):
        page = requests.get(url).content
        try:
            soup = get_soup(page)
            tag_div = soup.find('div', attrs={'class': 'download'})
            if not tag_div:
                raise UrlRewritingError('Unable to locate download link from url %s' % url)
            tag_a = tag_div.find('a')
            torrent_url = tag_a.get('href')
            # URL is sometimes missing the schema
            if torrent_url.startswith('//'):
                torrent_url = 'http:' + torrent_url
            return torrent_url
        except Exception, e:
            raise UrlRewritingError(e)

    @internet(log)
    def search(self, query, comparator=StringComparator(), config=None):
        """
        Search for name from piratebay.
        """
        if not isinstance(config, dict):
            config = {}
        sort = SORT.get(config.get('sort_by', 'seeds'))
        if config.get('sort_reverse'):
            sort += 1
        if isinstance(config.get('category'), int):
            category = config['category']
        else:
            category = CATEGORIES.get(config.get('category', 'all'))
        filter_url = '/0/%d/%d' % (sort, category)

        comparator.set_seq1(query)
        query = comparator.search_string()
        # urllib.quote will crash if the unicode string has non ascii characters, so encode in utf-8 beforehand
        url = 'http://thepiratebay.se/search/' + urllib.quote(query.encode('utf-8')) + filter_url
        log.debug('Using %s as piratebay search url' % url)
        page = requests.get(url).content
        soup = get_soup(page)
        entries = []
        for link in soup.find_all('a', attrs={'class': 'detLink'}):
            comparator.set_seq2(link.contents[0])
            log.debug('name: %s' % comparator.a)
            log.debug('found name: %s' % comparator.b)
            log.debug('confidence: %s' % comparator.ratio())
            if not comparator.matches():
                continue
            entry = Entry()
            entry['title'] = link.contents[0]
            entry['url'] = 'http://thepiratebay.se' + link.get('href')
            tds = link.parent.parent.parent.find_all('td')
            entry['torrent_seeds'] = int(tds[-2].contents[0])
            entry['torrent_leeches'] = int(tds[-1].contents[0])
            entry['search_ratio'] = comparator.ratio()
            entry['search_sort'] = torrent_availability(entry['torrent_seeds'], entry['torrent_leeches'])
            # Parse content_size
            size = link.find_next(attrs={'class': 'detDesc'}).contents[0]
            size = re.search('Size ([\.\d]+)\xa0([GMK])iB', size)
            if size:
                if size.group(2) == 'G':
                    entry['content_size'] = int(float(size.group(1)) * 1000 ** 3 / 1024 ** 2)
                elif size.group(2) == 'M':
                    entry['content_size'] = int(float(size.group(1)) * 1000 ** 2 / 1024 ** 2)
                else:
                    entry['content_size'] = int(float(size.group(1)) * 1000 / 1024 ** 2)
            entries.append(entry)

        if not entries:
            dashindex = query.rfind('-')
            if dashindex != -1:
                return self.search(query[:dashindex], comparator=comparator)
            else:
                raise PluginWarning('No close matches for %s' % query, log, log_once=True)

        entries.sort(reverse=True, key=lambda x: x.get('search_sort'))

        return entries

register_plugin(UrlRewritePirateBay, 'piratebay', groups=['urlrewriter', 'search'])
