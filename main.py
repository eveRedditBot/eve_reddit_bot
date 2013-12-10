import time
import praw
import yaml
import logging
import feedparser

from HTMLParser import HTMLParser
from pprint     import pprint

logging.basicConfig(format='%(asctime)s %(message)s',
                    datefmt='%m/%d/%Y %H:%M:%S',
                    level=logging.INFO)

class EVERedditBot():
    def __init__(self):
        self.config_path = 'config.yaml'

        stream = file(self.config_path, 'r')
        self.config = yaml.load(stream)
        stream.close()

    def run(self, sleep_time=None):
        logging.info('Default subreddit: /r/%s' %self.config['subreddit'])
        logging.info('Selected username: %s' %self.config['username'])
        logging.info('Submit stories to Reddit: %s' %self.config['submitpost'])
        raw_input("Press Enter to continue...")

        if sleep_time == None:
            sleep_time = self.config['sleep_time']

        while True:
            self.check_rss_feeds()
            logging.info('Sleeping for %d seconds.' %sleep_time)
            time.sleep(sleep_time)

    def postToReddit(self, data):
        r = praw.Reddit(self.config['api_header'])

        r.login(username=self.config['username'],
                password=self.config['password'])

        s = r.submit(data['subreddit'],
                     data['title'],
                     data['comments'][0])

        if len(data['comments']) > 1:
            c = s.add_comment(data['comments'][1])

        if len(data['comments']) > 2:
            del data['comments'][0]
            del data['comments'][0]

            for comment in data['comments']:
                c = c.reply(comment)

    def formatForReddit(self, feedEntry, postType, subreddit):
        if 'content' in feedEntry:
          content = feedEntry['content'][0]['value']
        else:
          content = feedEntry.description
        logging.debug(content)
        parser = EveRssHtmlParser()

        # Added the .replace because the parser does something funny to them and removes them before I can handle them
        parser.feed(content.replace('&nbsp;', ' ').replace('&bull;', '*'))
        parser.comments[0] = '%s\n\n%s' %(feedEntry['link'], parser.comments[0])
        parser.comments[-1] += self.config['signature']
        
        if 'author' in feedEntry:
          author = feedEntry['author']
        else:
          author = ''

        return {'comments': parser.comments,
                'link':     feedEntry['link'],
                'subreddit': subreddit,
                'title':    '[%s] %s ~%s' %(postType,
                                            feedEntry['title'],
                                            author)}

    def rss_parser(self, rss_feed):
        feed = feedparser.parse(self.config['rss_feeds'][rss_feed]['url'])

        if feed is None:
            logging.info('The following URL was returned nothing: %s' %url)
            return

        for entry in feed['entries']:
            if entry['id'] not in self.config['rss_feeds'][rss_feed]['stories']:
                logging.info('New %s! %s to /r/%s' %(self.config['rss_feeds'][rss_feed]['type'], entry['title'], self.config['rss_feeds'][rss_feed]['subreddit']))
                data = self.formatForReddit(entry, self.config['rss_feeds'][rss_feed]['type'], self.config['rss_feeds'][rss_feed]['subreddit'])

                self.config['rss_feeds'][rss_feed]['stories'].append(str(entry['id']))
                self.save_config()

                if self.config['submitpost'] == True:
                    self.postToReddit(data)

                    logging.info('Just posted to Reddit, sleeping for %d seconds' %self.config['sleep_time_post'])
                    time.sleep(self.config['sleep_time_post'])

                else:
                    logging.info('Skipping the submission...')

        return

    def check_rss_feeds(self):
        for rss_feed in self.config['rss_feeds']:
            self.rss_parser(rss_feed)

        self.save_config()

    def save_config(self):
        for rss_feed in self.config['rss_feeds']:
            self.config['rss_feeds'][rss_feed]['stories'].sort(reverse=True)

        stream = file(self.config_path, 'w')
        yaml.dump(self.config, stream, default_flow_style=False)
        stream.close()

class EveRssHtmlParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.comments = ['']
        self.cur_comment = 0
        self.max_comment_length = 8000
        self.cur_href = ''
        self.in_asterisk_tag = False
        self.in_a = False
        self.in_table = False
        self.first_row = False
        self.table_header = ''

    def handle_starttag(self, tag, attrs):
        if tag == 'p':
            if len(self.comments[self.cur_comment]) >= self.max_comment_length:
                self.cur_comment += 1
            
        elif tag == 'br':
            self.comments[self.cur_comment] += '\n\n'

        elif tag == 'em' or tag == 'i':
            self.in_asterisk_tag = True
            self.comments[self.cur_comment] += '*'
        
        elif tag == 'sup':
        	self.comments[self.cur_comment] += '^'

        elif tag == 'li':
            self.comments[self.cur_comment] += '* '

        elif tag == 'a':
            self.in_a = True

            for attr in attrs:
                if attr[0] == 'href':
                    self.cur_href = attr[1]

            self.comments[self.cur_comment] += '['

        elif tag == 'img':
            if not self.in_a:
                for attr in attrs:
                    if attr[0] == 'src':
                        self.cur_href = attr[1]

                self.comments[self.cur_comment] += '[image](%s)' %self.cur_href

            else:
                self.comments[self.cur_comment] += 'image'

        elif tag == 'strong' or tag == 'b':
            self.in_asterisk_tag = True
            self.comments[self.cur_comment] += '**'

        elif tag == 'h1':
            self.comments[self.cur_comment] += '#'

        elif tag == 'h2':
            self.comments[self.cur_comment] += '##'

        elif tag == 'h3':
            self.comments[self.cur_comment] += '###'

        elif tag == 'h4':
            self.comments[self.cur_comment] += '####'

        elif tag == 'h5':
            self.comments[self.cur_comment] += '#####'

        elif tag == 'h6':
            self.comments[self.cur_comment] += '######'

        elif tag == 'table':
            self.in_table = True
            self.first_row = True

        elif tag == 'tbody':
            pass
        	
        elif tag == 'tr':
            pass
            
        elif tag == 'ul':
        	pass
        
        elif tag == 'span':
        	pass
        
        elif tag == 'font':
        	pass
        	
        elif tag == 'u':
        	pass
        
        elif tag == 'div':
        	pass

        elif tag == 'td':
            self.comments[self.cur_comment] += '| '

            if self.first_row:
                self.table_header += '|:-'

        else:
            print "Encountered an unhandled start tag:", tag

    def handle_endtag(self, tag):
        self.in_asterisk_tag = False
    	endswithspace = self.comments[self.cur_comment].endswith(' ')
        if tag == 'p' or tag == 'br':
            if not self.in_table:
                self.comments[self.cur_comment] += '\n\n'

        elif tag == 'em' or tag == 'i':
            if endswithspace:
                self.comments[self.cur_comment] = self.comments[self.cur_comment].rstrip()
                self.comments[self.cur_comment] += '* '
            else:
                self.comments[self.cur_comment] += '*'

        elif tag == 'ul':
            self.comments[self.cur_comment] += '\n\n'

        elif tag == 'li':
            self.comments[self.cur_comment] += '\n'

        elif tag == 'a':
            self.in_a = False
            self.comments[self.cur_comment] += '](%s)' %self.cur_href

        elif tag == 'strong' or tag == 'b':
            self.comments[self.cur_comment] = self.comments[self.cur_comment].rstrip()
            self.comments[self.cur_comment] += '** '

        elif tag == 'h1':
            self.comments[self.cur_comment] += '#\n\n'

        elif tag == 'h2':
            self.comments[self.cur_comment] += '##\n\n'

        elif tag == 'h3':
            self.comments[self.cur_comment] += '###\n\n'

        elif tag == 'h4':
            self.comments[self.cur_comment] += '####\n\n'

        elif tag == 'h5':
            self.comments[self.cur_comment] += '#####\n\n'

        elif tag == 'h6':
            self.comments[self.cur_comment] += '######\n\n'

        elif tag == 'table':
            self.in_table = False

        elif tag == 'tr':
            if self.first_row:
                self.comments[self.cur_comment] += '|\n%s' %self.table_header
                self.first_row = False
                self.table_header = ''

            self.comments[self.cur_comment] += '|\n'

    def handle_data(self, data):
        data = data.strip('\n\t')
        if self.in_asterisk_tag:
            data = data.lstrip()

        if (len(self.comments[self.cur_comment]) + len(data)) >= self.max_comment_length:
            self.cur_comment += 1
            self.comments.append('')

        self.comments[self.cur_comment] += data

if __name__ == '__main__':
    bot = EVERedditBot()
    bot.run()
