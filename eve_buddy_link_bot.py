import praw             
import sys              
import time             
import logging
import warnings
import yaml
import re
import random
import os
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
_username = os.environ.get('BUDDY_BOT_USER_NAME', _config['username'])
_password = os.environ.get('BUDDY_BOT_PASSWORD', _config['password'])
_enabled = _config['enabled']
_sleeptime = _config['sleep_time']
_signature = _config['signature']
_home_subreddit = _config['home_subreddit']
_last_daily_job = datetime.now() + relativedelta( days = -2 )
_once = os.environ.get('BUDDY_BOT_RUN_ONCE', 'False') == 'True'

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
                purge_old_providers(r)
                _last_daily_job = datetime.now()
            
            scan_messages(r)
            scan_submissions(r)
            scan_threads(r)
            
            if (sleeptime > (_sleeptime)):
                sleeptime = int(sleeptime/2)
            
        except Exception as e:
            #exponential sleeptime back-off
            #if not successful, slow down.
            
            catchable_exceptions = ["Gateway Time", "timed out", "ConnectionPool", "Connection reset", "Server Error", "try again", "Too Big", "onnection aborted"]
            if any(substring in str(e) for substring in catchable_exceptions):
                sleeptime = round(sleeptime*2)
                logging.debug(str(e))
            else:
                exitexception(e)
        if (_once):
        	logging.info('running once') 
        	break
        if (sleeptime > (_sleeptime)):
            logging.info("Sleeping for %s seconds", str(sleeptime))
        else:
            logging.info("Sleeping for %s seconds", str(sleeptime))
        time.sleep(sleeptime)

def print_followed_subreddits(r):
    subreddits_to_follow = []
    for subreddit in r.get_my_subreddits():
        name = subreddit.display_name.lower()
        logging.info('\tfollowing ' + name)

def get_threads_to_follow(r):
    threads_to_follow = []
    #logging.info('refreshing saved links to follow')
    for thread in r.user.get_saved():
        #name = thread.url
        #logging.info('\tfollowing ' + name)
        threads_to_follow.append(thread)
    return threads_to_follow

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
        if (message.author is None):
            continue
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
            message.reply('your ' + type +' link was invalid soz. Send ONLY the link in the body of the message. No other text. Please try again.')
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

def scan_threads(session):
    threads = get_threads_to_follow(session)
    for thread in threads:
        logging.debug('\tChecking ' + thread.url)
        thread.replace_more_comments(limit=None, threshold=0)
        # just getting top-level comments
        all_comments = thread.comments
        comment_count = 0
        for comment in all_comments:
            comment_count += 1
            index = str(comment_count)
            text = comment.body
            if is_probably_actionable(text):
              actionable = True
              # Check replies to see if already replied
              for reply in comment.replies:
                if reply.author == None:
                    logging.debug("No author for comment #" + index)
                    continue
                if reply.banned_by is not None:
                    logging.debug("Detected a banned comment")
                    logging.debug(reply.banned_by)             
                    if (reply.banned_by == True):
                      logging.debug("Found reply by " + reply.author.name + " but it was banned")
                    elif (reply.banned_by.name == _username):
                      logging.debug("Found reply by " + reply.author.name + " but it was banned by me")
                      continue
                    else:
                      logging.debug("Found reply by " + reply.author.name + " but it was banned by " + str(vars(reply.banned_by)))
                if reply.author.name == _username:
                    logging.debug("Already replied to comment #" + index)
                    actionable = False
                    break
                
                # you know what? for now, if anyone has beat us, skip;
                logging.debug("comment #" + index + " already has a reply by " + reply.author.name + "; skipping")
                actionable = False
                break

              # If not already replied
              if (actionable == True):
                logging.debug("Actionable comment found at comment #" + index)
                logging.debug("replying to " + comment.permalink)
                post_reply(session, comment, text)
                time.sleep(2)
              

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
                    if (reply.subreddit.display_name.lower() == _home_subreddit and
                            reply.banned_by == True):
                        logging.info('unbanning my own comment')
                        reply.approve()
                    actionable = False
                    break
                if reply.banned_by is not None:
                    logging.debug("Detected a banned comment")                 
                    if (reply.banned_by == True):
                      logging.debug("Found reply by " + reply.author.name + " but it was banned")
                    elif (reply.banned_by.name == _username):
                      logging.debug("Found reply by " + reply.author.name + " but it was banned by me")
                      continue
                    else:
                      logging.debug("Found reply by " + reply.author.name + " but it was banned by " + str(vars(reply.banned_by)))
                    
                # you know what? for now, if anyone has beat us, skip;
                logging.debug("submission #" + index + " already has a reply by " + reply.author.name + "; skipping")
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
        response+= provider['url'] + '\n\n'
        response+= '~As part of the agreement of using this bot, they must give you *at '
        response+= 'least 75%* of the rewards they receive if you subscribe~\n\n'
        response+='Enjoy!'
    
    response+='\n\n&nbsp;\n\n&nbsp;\n\n'
    response+='^(*If this message isn\'t helpful or you think it was posted in error, '
    response+='respond to this comment and let me know, or feel free to have the comment '
    response+='removed by a moderator.*)\n\n'

    if _enabled:
        subreddit_name = thing.subreddit.display_name.lower()
        provider_name = provider['username'] if (provider is not None) else 'Nobody'
        
        
        try:        
            if (hasattr(thing, 'add_comment')):
                thing.add_comment(response + _signature)
            else: 
                thing.reply(response + _signature)
        except Exception as e:            
            catchable_exceptions = ["that user doesn't exist", "that comment has been deleted"]
            if any(substring in str(e) for substring in catchable_exceptions):
                logging.debug(str(e))
                return
            else:
                exitexception(e)
        
        logging.info(provider_name + ' provided a ' + link_type + ' link to ' + recipient + ' in /r/' + subreddit_name)
        if (hasattr(thing, 'url')):
            url = thing.url
        else:
            url = thing.permalink
        
        if (provider is not None):
            notify_provider(r, link_type, provider['username'], recipient, url)
        
    else:
        logging.info('disabled, but would have replied: ' + response)


def notify_provider(session, link_type, username, recipient, url):
    subject = link_type + ' link sent to ' + recipient
    msg = 'Hi. I sent a link on your behalf. Check it out here:\n\n' + url
    session.send_message(username, subject, msg)

def notify_link_removal(session, link_type, recipient, url):
    subject = link_type + ' link expired and removed'
    msg = 'Hi ' + recipient + '.\n\n'
    msg+='The link you have provided has expired. Links are valid for a few months '
    msg+= ' then retired, in case you are no longer playing.\n\n'
    msg+= 'You are welcome to resubmit your link in the '
    msg+= '[usual manner](http://www.reddit.com/message/compose/?to='
    msg+= _username
    msg+= '&subject=add ' + link_type
    msg+= '&message=' + url.replace('&', '%26') + ').'
    session.send_message(recipient, subject, msg)

def purge_old_providers(session):
    expiration_threshold = datetime.now() + relativedelta( months = -3)
    for key in _config['links'].keys():
        purge_old_providers_of_type(session, key, expiration_threshold)

def purge_old_providers_of_type(session, key, expiration_threshold):
    logging.info('purging old ' + key + ' providers')
    if _links[key]:
        old_providers = [provider for provider in _links[key] 
                 if provider['added'] < expiration_threshold]
        for old_provider in old_providers[:]:
            old_username = old_provider['username']
            logging.info('\tdetected old ' + key + ' link from ' + old_username)
            try:
              notify_link_removal(session, key, old_username, old_provider['url'])
            except Exception as e:            
              catchable_exceptions = ["that user doesn't exist"]
              if any(substring in str(e) for substring in catchable_exceptions):
                logging.debug(str(e))
              else:
                exitexception(e)
            
            _links[key].remove(old_provider)
            writeYamlFile(_links, _links_file_name)
            time.sleep(2)


def get_flair_text(session, username):
    flair = session.get_flair(_home_subreddit, username)
    if (flair is None):
        flair_text = ''
    else:
        flair_text = flair['flair_text']
    return flair_text

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
