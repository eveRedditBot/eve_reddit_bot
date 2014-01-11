import socket
import time
import praw
import yaml
import re
import logging
import feedparser
import sys, getopt

from HTMLParser import HTMLParser
from pprint     import pprint
from datetime   import datetime
from bs4        import UnicodeDammit

logging.basicConfig(format='%(asctime)s %(message)s',
                    datefmt='%m/%d/%Y %H:%M:%S',
                    level=logging.INFO)

class EVERedditBot():
    def __init__(self):
        requests_log = logging.getLogger("requests")
        requests_log.setLevel(logging.WARNING)
        
        socket.setdefaulttimeout(10)
        self.config_path = 'config.yaml'

        stream = file(self.config_path, 'r')
        self.config = yaml.load(stream)
        stream.close()
        self.subreddit = self.config['subreddit']
        self.username = self.config['username']
        self.password = self.config['password']
        self.submitpost = self.config['submitpost']

    def run(self, sleep_time=None):
        logging.info('Default subreddit: /r/%s' %self.subreddit)
        logging.info('Selected username: %s' %self.username)
        logging.info('Submit stories to Reddit: %s' %self.submitpost)
        #raw_input("Press Enter to continue...")

        if sleep_time == None:
            sleep_time = self.config['sleep_time']

        while True:
            self.check_rss_feeds()
            self.check_downvoted_submissions()
            logging.info('Sleeping for %d seconds.' %sleep_time)
            time.sleep(sleep_time)

    def initReddit(self):
        r = praw.Reddit(self.config['api_header'])
        return r

    def loginToReddit(self, r):
        r.login(username=self.username,
                password=self.password)
        return r
    
    def postToReddit(self, data):
        r = self.loginToReddit(self.initReddit())
        
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

    def formatForReddit(self, feedEntry, postType, subreddit, raw):
        if 'content' in feedEntry:
          content = feedEntry['content'][0]['value']
        else:
          content = feedEntry.description
        logging.debug(content)
        parser = EveRssHtmlParser()
        
        title = feedEntry['title']

        # some feeds like Twitter are raw so the parser hates it.
        if (raw):
          regex_of_url = '(https?:\/\/[\da-z\.-]+\.[a-z\.]{2,6}[\/\w&\.-\?]*)'
          title = re.sub(regex_of_url, '', title)
          clean_content = re.sub(regex_of_url, '<a href="\\1">link</a>', content)
          clean_content = UnicodeDammit.detwingle(clean_content)
          #logging.info(clean_content)
          u = UnicodeDammit(clean_content, 
                      smart_quotes_to='html', 
                      is_html = False )
          # fix twitter putting ellipses on the end
          content = u.unicode_markup.replace(unichr(8230),' ...')
          logging.debug('.....')
        
        # Added the .replace because the parser does something funny to them and removes them before I can handle them
        parser.feed(content.replace('&nbsp;', ' ').replace('&bull;', '*'))
        parser.comments[0] = '%s\n\n%s' %(feedEntry['link'], parser.comments[0])
        parser.comments[-1] += self.config['signature']
        
        if 'author' in feedEntry:
          author = '~' + feedEntry['author']
        else:
          author = ''

        return {'comments': parser.comments,
                'link':     feedEntry['link'],
                'subreddit': subreddit,
                'title':    '[%s] %s %s' %(postType,
                                            title,
                                            author)}

    def rss_parser(self, rss_feed):
        feed = feedparser.parse(self.config['rss_feeds'][rss_feed]['url'])

        if feed is None:
            logging.info('The following URL was returned nothing: %s' %url)
            return

        for entry in feed['entries']:
            if entry['id'] not in [ story['posturl'] for story in self.config['rss_feeds'][rss_feed]['stories'] ]:
                logging.info('New %s! %s to /r/%s' %(self.config['rss_feeds'][rss_feed]['type'], entry['title'], self.config['rss_feeds'][rss_feed]['subreddit']))
                data = self.formatForReddit(entry, self.config['rss_feeds'][rss_feed]['type'], self.config['rss_feeds'][rss_feed]['subreddit'], self.config['rss_feeds'][rss_feed]['raw'])

                self.config['rss_feeds'][rss_feed]['stories'].append({'posturl': str(entry['id']), 'date': datetime.now()})
                self.save_config()

                if self.submitpost == True:
                    self.postToReddit(data)

                    logging.info('Just posted to Reddit, sleeping for %d seconds' %self.config['sleep_time_post'])
                    time.sleep(self.config['sleep_time_post'])

                else:
                    logging.info('Skipping the submission...')
                    logging.info(data)

        return

    def check_rss_feeds(self):
        for rss_feed in self.config['rss_feeds']:
            self.rss_parser(rss_feed)

        self.save_config()
        
    def check_downvoted_submissions(self):
        r = self.initReddit()
        user = r.get_redditor(self.username)
        submitted = user.get_submitted(sort='new', limit=25)
        downvoted_submissions = [submission for submission in submitted if submission.score <= -4]
        
        if (downvoted_submissions):
            r = self.loginToReddit(r)
            for submission in downvoted_submissions:
                if self.submitpost == True:
                    logging.info('deleting %s (score: %d)', submission.url, submission.score)
                    submission.delete()
                else:
                    logging.info('detected %s (score: %d), skipping', submission.url, submission.score)

    def save_config(self):
        for rss_feed in self.config['rss_feeds']:
            self.config['rss_feeds'][rss_feed]['stories'].sort(key=lambda x: x['date'], reverse=True)

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

        elif tag == 'hr':
            self.comments[self.cur_comment] += '\n\n-----\n\n'

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
        
        elif tag == 'strike' or tag == 's':
            self.in_asterisk_tag = True
            self.comments[self.cur_comment] += '~~'

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
        
        elif tag == 'strike' or tag == 's':
            self.comments[self.cur_comment] = self.comments[self.cur_comment].rstrip()
            self.comments[self.cur_comment] += '~~ '

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
    
    try:
      opts, args = getopt.getopt(sys.argv[1:],"",["help","username=","password=","submit=","subreddit="])
    except getopt.GetoptError:
      print 'main.py --help'
      sys.exit(2)
    for opt, arg in opts:
      if opt in ("--help"):
         print 'main.py -u <username> -p <password> --submit=<(True|False)> --subreddit=<subreddit>'
         print '  any missing arguments will be taken from config.yaml'
         sys.exit()
      elif opt in ("--username"):
         bot.username = arg
      elif opt in ("--password"):
         bot.password = arg
      elif opt in ("--subreddit"):
         bot.subreddit = arg
      elif opt in ("--submit"):
         bot.submitpost = arg

    bot.run()
