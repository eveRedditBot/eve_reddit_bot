import socket
import time
import praw
import yaml
import re
import logging
import warnings
import feedparser
import sys, getopt

from HTMLParser import HTMLParser
from pprint     import pprint
from datetime   import datetime, timedelta
from dateutil.relativedelta import relativedelta
from bs4        import UnicodeDammit

logging.basicConfig(format='%(asctime)s %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S',
                    level=logging.INFO)

class EVERedditBot():
    def __init__(self):
        requests_log = logging.getLogger("requests")
        requests_log.setLevel(logging.WARNING)
        warnings.filterwarnings('ignore', message='.*equal comparison failed.*')
        
        socket.setdefaulttimeout(20)
        self.config_path = 'eve_reddit_bot_config.yaml'
        self.config = self.readYamlFile(self.config_path)
        self.feed_config_path = 'eve_reddit_bot_feeds.yaml'
        self.feed_config = self.readYamlFile(self.feed_config_path)
        self.subreddit = self.config['subreddit']
        self.username = self.config['username']
        self.password = self.config['password']
        self.submitpost = self.config['submitpost']
        self.once = self.config['run_once']
        self.admin_email = None
        
    def readYamlFile(self, path):
        with open(path, 'r') as infile:
           return yaml.load(infile)

    def writeYamlFile(self, yaml_object, path):
        with open(path, 'w') as outfile:
           outfile.write( yaml.dump(yaml_object, default_flow_style=False) )
    
    
    def run(self):
        self.reddit = self.loginToReddit(self.initReddit())
        self.check_rss_feeds()
        self.check_downvoted_submissions()

    def initReddit(self):
        r = praw.Reddit(self.config['api_header'])
        return r

    def loginToReddit(self, r):
        r.login(username=self.username,
                password=self.password)
        return r
    
    def postToReddit(self, data):
        s = self.reddit.submit(data['subreddit'],
                     data['title'],
                     data['comments'][0])

        if len(data['comments']) > 1:
            c = s.add_comment(data['comments'][1])

        if len(data['comments']) > 2:
            del data['comments'][0]
            del data['comments'][0]

            for comment in data['comments']:
                time.sleep(5)
                c = c.reply(comment)

    def formatForReddit(self, feedEntry, postType, subreddit, raw):
        if 'content' in feedEntry:
          content = feedEntry['content'][0]['value']
        elif 'description' in feedEntry:
          content = feedEntry.description
        else:
          content = ''
        logging.debug(content)
        parser = EveRssHtmlParser()
        
        title = feedEntry['title']

        # some feeds like Twitter are raw so the parser hates it.
        if (raw):
          regex_of_url = '(https?:\/\/[\dA-z\.-]+\.[A-z\.]{2,6}[\/\w&=#\.\-\?]*)'
          title = re.sub(regex_of_url, '', title)
          clean_content = content.replace(' pic.twitter.com', ' http://pic.twitter.com')
          clean_content = re.sub(regex_of_url, '<a href="\\1">link</a>', clean_content)
          clean_content = UnicodeDammit.detwingle(clean_content)
          #logging.info(clean_content)
          u = UnicodeDammit(clean_content, 
                      smart_quotes_to='html', 
                      is_html = False )
          # fix twitter putting ellipses on the end
          content = u.unicode_markup.replace(unichr(8230),' ...')
          logging.debug('.....')
        
        # Added the .replace because the parser does something funny to them and 
        # removes them before I can handle them
        content = content.replace('&nbsp;', ' ')
        content = content.replace('&bull;', '*').replace('&middot;','*')
        content = content.replace('&ldquo;','\'').replace('&rdquo;','\'')
        content = re.sub('( [ ]+)', ' ', content)
        parser.feed(content)
        parser.comments[0] = '%s\n\n%s' %(feedEntry['link'], parser.comments[0])
        parser.comments[-1] += self.config['signature']
        
        if 'author' in feedEntry:
          author = '~' + feedEntry['author']
        else:
          author = ''

        return {'comments': parser.comments,
                'link':     feedEntry['link'],
                'subreddit': subreddit,
                'title':    '[%s] %s %s' %(postType, title, author)}

    def rss_parser(self, rss_feed, all_entry_ids):
        feed_config = self.feed_config['rss_feeds'][rss_feed]
        feed = feedparser.parse(feed_config['url'])
        stories = feed_config['stories']

        if feed is None:
            logging.info('The following URL was returned nothing: %s' %url)
            return

        for entry in feed['entries']:
            all_entry_ids.append(entry['id'])
            if entry['id'] not in [ story['posturl'] for story in stories ]:
                logging.info('New %s! %s to /r/%s' %(feed_config['type'], entry['title'], 
                    feed_config['subreddit']))
                data = self.formatForReddit(entry, feed_config['type'], 
                    feed_config['subreddit'], feed_config['raw'])

                self.feed_config['rss_feeds'][rss_feed]['stories'].append(
                    {'posturl': str(entry['id']), 'date': datetime.now()})

                if self.submitpost == True:
                    self.postToReddit(data)
                    logging.info('Posted to Reddit')
                    self.save_feed_config()
                    return

                else:
                    logging.info('Skipping the submission...')
                    logging.info(data)
                
        return
    
    def prune_old_stories(self, all_entry_ids, threshold):
        for feed in self.feed_config['rss_feeds']:
          stories = self.feed_config['rss_feeds'][feed]['stories']
          for story in stories[:]:
            if (story['posturl'] not in [all_entry_ids] and (story['date'] < threshold)):
              logging.info('detected old story %s from %s' %(story['posturl'], story['date']))
              stories.remove(story)
        self.save_feed_config()
        return

    def check_rss_feeds(self):
        all_entry_ids = []
        for rss_feed in self.feed_config['rss_feeds']:
            self.rss_parser(rss_feed, all_entry_ids)

        many_months_ago = datetime.now() + relativedelta( months = -18 )
        self.prune_old_stories(all_entry_ids, many_months_ago)
        self.save_feed_config()
        
    def check_downvoted_submissions(self):
        user = self.reddit.get_redditor(self.username)
        submitted = user.get_submitted(sort='new', limit=25)
        downvoted_submissions = [submission for submission in submitted if (
            submission.ups - submission.downs) <= -4]
        
        if (downvoted_submissions):
            for submission in downvoted_submissions:
                true_score = submission.ups - submission.downs
                if self.submitpost == True:
                    logging.info('deleting %s (score: %d)', submission.url, true_score)
                    submission.delete()
                else:
                    logging.info('detected %s (score: %d), skipping', submission.url, true_score)

    def save_feed_config(self):
        for rss_feed in self.feed_config['rss_feeds']:
            self.feed_config['rss_feeds'][rss_feed]['stories'].sort(key=lambda x: x['date'], reverse=True)

        self.writeYamlFile(self.feed_config, self.feed_config_path)


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
        self.in_list = False
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
            self.in_list = True
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
            self.comments[self.cur_comment] += '\n#'

        elif tag == 'h2':
            self.comments[self.cur_comment] += '\n##'

        elif tag == 'h3':
            self.comments[self.cur_comment] += '\n###'

        elif tag == 'h4':
            self.comments[self.cur_comment] += '\n####'

        elif tag == 'h5':
            self.comments[self.cur_comment] += '\n#####'

        elif tag == 'h6':
            self.comments[self.cur_comment] += '\n######'

        elif tag == 'table':
            self.in_table = True
            self.first_row = True

        elif tag == 'tbody':
            pass
        	
        elif tag == 'tr':
            pass
            
        elif tag == 'ul' or tag == 'ol':
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

        elif tag == 'ul' or tag == 'ol':
            self.comments[self.cur_comment] += '\n\n'

        elif tag == 'li':
            self.in_list = False
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
            last_comment = self.cur_comment
            self.cur_comment += 1
            self.comments.append('')
            # Don't leave hanging <li>
            if (self.in_list and self.comments[last_comment].endswith('* ')):
                self.comments[last_comment] = self.comments[last_comment][:-2]
                self.handle_starttag('li', None)

        self.comments[self.cur_comment] += data
        

# exit hook
def exitexception(e):
     #TODO re-add if required
     #print ("Error ", str(e))
     #exit(1)
     raise



if __name__ == '__main__':
    bot = EVERedditBot()
    allowed_args = ["help","username=","password=","submit=","subreddit=","email="]
    
    try:
      opts, args = getopt.getopt(sys.argv[1:],"",allowed_args)
    except getopt.GetoptError:
      print 'main.py --help'
      sys.exit(2)
    for opt, arg in opts:
      if opt in ("--help"):
         print 'main.py -u <username> -p <password> --submit=<(true|false)>'
         print '    --subreddit=<subreddit> --email=<email address>'
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
      elif opt in ("--email"):
         bot.admin_email = arg
    
    logging.info('Default subreddit: /r/%s', bot.subreddit)
    logging.info('Selected username: %s', bot.username)
    logging.info('Submit stories to Reddit: %s', bot.submitpost)
    if bot.admin_email != None: 
        logging.info('Admin emails to: %s', bot.admin_email)
    
    _sleeptime = bot.config['sleep_time']
    
    while(True):
        try:
            bot.run()
            if (_sleeptime > (bot.config['sleep_time'])):
                _sleeptime = round(_sleeptime/2)
        
        except Exception as e:
            #exponential sleeptime back-off
            #if not successful, slow down.
            
            catchable_exceptions = ["Gateway Time", "timed out", "HTTPSConnectionPool", "Connection reset", "Server Error", "try again"]
            if any(substring in str(e) for substring in catchable_exceptions):
                _sleeptime = round(_sleeptime*2)
                logging.debug(str(e))
            else:
                exitexception(e)

        #if sleeping for a long time, email admin.
        if (_sleeptime > (bot.config['sleep_time'] * 2) and bot.admin_email != None):
            emailcommand = 'echo "The bot is sleeping for ' + str(round(_sleeptime/60)) + ' minutes." | mutt -s "ALERT: BOT IS SLEEPING" -- root '+bot.admin_email
            logging.info(emailcommand)
            #result = subprocess.call(emailcommand, shell=True)
        if (bot.submitpost):
            logging.info("Sleeping for %s minutes", str(_sleeptime/60))
            time.sleep(_sleeptime)

#end
