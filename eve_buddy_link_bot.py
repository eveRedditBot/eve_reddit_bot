import praw             
import sys              
import time             
import logging
import warnings
import yaml
import re
import random
from decimal    import Decimal
from datetime   import datetime
from dateutil.relativedelta import relativedelta

logging.basicConfig(format='%(asctime)s %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S',
                    level=logging.INFO)
#                    level=logging.DEBUG)
requests_log = logging.getLogger("requests")
requests_log.setLevel(logging.WARNING)
_sleeptime = 60

def readYamlFile(path):
    with open(path, 'r') as infile:
        return yaml.load(infile)

def writeYamlFile(yaml_object, path):
        with open(path, 'w') as outfile:
           outfile.write( yaml.dump(yaml_object, default_flow_style=False ))

_config_file_name = 'eve_buddy_link_bot_config.yaml'
_config = readYamlFile(_config_file_name)
_links_file_name = 'eve_buddy_link_bot_links.yaml'
_links = readYamlFile(_links_file_name)
_api_header = _config['api_header']
_username = _config['username']
_password = _config['password']
_enabled = _config['enabled']
_sleeptime = _config['sleep_time']
_signature = _config['signature']
_last_daily_job = datetime.now() + relativedelta( days = -2 )

def main():
    global _last_daily_job
    sleeptime = _sleeptime
    r = praw.Reddit(_api_header)
    r.login(_username, _password)
    #r.config.decode_html_entities = True
    logging.info('Logged into reddit as ' + _username)
    
    while(True):
        try:
            if (should_do_daily_jobs()):
                # put jobs here, e.g. clearing out old links
                print_followed_subreddits(r)
                _last_daily_job = datetime.now()
            
            scan_messages(r)
            scan_submissions(r)
            
            if (sleeptime > (_sleeptime)):
                sleeptime = int(sleeptime/2)
            
            logging.info("Sleeping for %s seconds", str(sleeptime))
            time.sleep(sleeptime)
        except Exception as e:
            #exponential sleeptime back-off
            #if not successful, slow down.
            
            catchable_exceptions = ["Gateway Time", "timed out", "ConnectionPool", "Connection reset", "Server Error", "try again", "Too Big"]
            if any(substring in str(e) for substring in catchable_exceptions):
                sleeptime = round(sleeptime*2)
                logging.debug(str(e))
            else:
                exitexception(e)

def print_followed_subreddits(r):
    subreddits_to_follow = []
    for subreddit in r.get_my_subreddits():
        name = subreddit.display_name.lower()
        logging.info('\tfollowing ' + name)

# TODO follow particular threads as well?
#def get_threads_to_follow(r):
#    threads_to_follow = []
#    logging.info('refreshing saved links to follow')
#    for thread in r.user.get_saved():
#        name = thread.url
#        logging.info('\tfollowing ' + name)
#        threads_to_follow.append(thread)
#    return threads_to_follow

# exit hook
def exitexception(e):
     #TODO re-add if required
     #print ("Error ", str(e))
     #exit(1)
     raise

def is_probably_actionable(text):
    return get_link_type(text) is not None

def get_link_type(text):
    for link_type in _config['links']:
      for regex in _config['links'][link_type]['regexes']:
        #TODO optimise regex compilation
        found = re.compile(regex, re.IGNORECASE).search(text)
        name = _config['links'][link_type]['name']
        if(found):
          return name
          
    return None

def scan_messages(session):
    unread = [message for message in session.get_unread() if message.was_comment == False 
                and message.subject in ('add trial', 'add recall')]
    for message in unread:
        time.sleep(2)
        author = str(message.author.name)
        subject = str(message.subject)
        body = str(message.body).replace('&amp;', '&') # minimal decoding
        if(subject == "add recall"):
            type = 'recall'
            valid = body.startswith('https://secure.eveonline.com/RecallProgram/?invc=')
        else:
            type = 'trial'
            valid = body.startswith('https://secure.eveonline.com/trial/?invc=')
        
        if (not valid):
            message.reply('your ' + type +' link was invalid soz.')
            logging.info('discarded invalid ' + type + ' message from ' + author)
            message.mark_as_read()
            continue
        
        is_duplicate = [link for link in _links[type] if link['url'] == body or link['username'] == author]
        if (is_duplicate):
            message.reply('You already have a ' + type + ' link. Get out.')
            logging.info('discarded duplicate ' + type + ' message from ' + author)
            message.mark_as_read()
            continue
        
        _links[type].append({
            'username': author,
            'url': body,
            'added': datetime.now()
        })
        writeYamlFile(_links, _links_file_name)
        message.reply('added a ' + type + ' link for you kthxbye.')
        logging.info('added a ' + type + ' link for ' + author)
        
        message.mark_as_read()


def scan_submissions(session):
    submission_limit = 10
    submissions = session.get_new(limit = submission_limit)
    
    submission_count = 0   # Number of submissions scanned (for logging)

    # Read each submission
    for scanning in submissions:
        submission_count += 1
        index = str(submission_count)
        display_name = scanning.subreddit.display_name.lower()
        logging.debug('submission ' + index + ' from ' + display_name)
        text = None
        if hasattr(scanning, 'body'):
            text = scanning.body
        elif hasattr(scanning, 'selftext'):
            text = scanning.selftext
        else:
            logging.debug('skipping submission #' + index + ' because ' + str(type(scanning)))
            continue
        
        if hasattr(scanning, 'title'):
            text+= scanning.title
        if is_probably_actionable(text):

            actionable = True
            # Check replies to see if already replied
            for reply in scanning.replies if hasattr(scanning, 'replies') else scanning.comments:
                if reply.author == None:
                    logging.debug("No author for submission #" + index)
                    continue
                if reply.author.name == _username:
                    logging.debug("Already replied to submission #" + index)
                    actionable = False
                    break
                # you know what? for now, if anyone has beat us, skip;
                logging.debug("submission #" + index + " already has replies; skipping")
                actionable = False
                break

            # If not already replied
            if (actionable == True):
                logging.debug("Actionable submission found at submission #" + index)
                logging.debug("replying to " + scanning.url)
                post_reply(session, scanning, text)
                time.sleep(2)
                
        if (submission_count > submission_limit):
            #Reddit API is being too generous; quit early, go home, play with the kids
            logging.debug('reached limit, breaking off')
            break

def post_reply(r, thing, text):
    recipient = str(thing.author.name)
    link_type = get_link_type(text)
    if (link_type is None):
        # shouldn't, but regex mistakes do happen
        return
    
    if recipient == None:
        logging.info('could not determine recipient; probably deleted.')
        return 
    response = 'Hi. It looks like you\'re looking for a ' + link_type +' link.\n\n'
    provider = get_link_provider(link_type)
    if (provider is None):
        response+= 'I don\'t think those links are available any more.'
    else:
        response+= '/u/' + provider['username'] + ' has offered theirs:\n\n'
        response+= provider['url'] + '\n\nEnjoy!'
    
    response+='\n\n&nbsp;\n\n&nbsp;\n\n'
    response+='^(*If this message isn\'t helpful or you think it was posted in error, '
    response+='respond to this comment and let me know, or feel free to have the comment '
    response+='removed by a moderator.*)\n\n'

    

    if _enabled:
        subreddit_name = thing.subreddit.display_name.lower()
        provider_name = provider['username'] if (provider is not None) else 'Nobody'
        logging.info(provider_name + ' provided a ' + link_type + ' link to ' + recipient + ' in /r/' + subreddit_name)
        #reply only works on comments
        #thing.reply(response + _signature)
        
        thing.add_comment(response + _signature)
        
        if (provider is not None):
            notify_provider(r, link_type, provider['username'], recipient, thing.url)
        
    else:
        logging.info('disabled, but would have replied: ' + response)

def notify_provider(session, link_type, username, recipient, url):
    subject = link_type + ' link sent to ' + recipient
    msg = 'Hi. I sent a link on your behalf. Check it out here:\n\n' + url
    session.send_message(username, subject, msg)
    

# randomly find someone who offers that type of link
def get_link_provider(link_name):
    link_key = [key for key in _config['links'].keys() if _config['links'][key]['name'] == link_name]
    for link in link_key:
        return random.choice(_links[link])
    
    return None # shouldn't happen, but maybe that type is empty.

def should_do_daily_jobs():
    return datetime.now() > _last_daily_job + relativedelta(days = 1)


if __name__ == '__main__':
    main()
