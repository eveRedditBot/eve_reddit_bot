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
#                    level=logging.INFO)
                    level=logging.DEBUG)
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
_last_refreshed_subreddits = datetime.now() + relativedelta( days = -2 )

def main():
    global _last_refreshed_subreddits
    sleeptime = _sleeptime
    r = praw.Reddit(_api_header)
    r.login(_username, _password)
    r.config.decode_html_entities = True
    logging.info('Logged into reddit as ' + _username)
    
    while(True):
        try:
            if (should_refresh_subreddits()):
                followed_subreddits = get_subreddits_to_follow(r)
                _last_refreshed_subreddits = datetime.now()
            
            scan_for_messages(r)
            scan_for_comments(r, followed_subreddits)
            
            if (sleeptime > (_sleeptime)):
                sleeptime = round(sleeptime/2)
        
        except Exception as e:
            #exponential sleeptime back-off
            #if not successful, slow down.
            
            catchable_exceptions = ["Gateway Time", "timed out", "ConnectionPool", "Connection reset", "Server Error", "try again", "Too Big"]
            if any(substring in str(e) for substring in catchable_exceptions):
                sleeptime = round(sleeptime*2)
                logging.debug(str(e))
            else:
                exitexception(e)

        if (_enabled):
            logging.info("Sleeping for %s seconds", str(sleeptime))
            time.sleep(sleeptime)
        else: 
            exit(0)

def get_subreddits_to_follow(r):
    subreddits_to_follow = []
    logging.info('refreshing followed subreddits')
    for subreddit in r.get_my_subreddits():
        name = subreddit.display_name.lower()
        logging.info('\tfollowing ' + name)
    return subreddits_to_follow

# TODO follow particular threads as well?
#def get_threads_to_follow(r):
#    threads_to_follow = []
#    logging.info('refreshing saved links to follow')
#    for thread in r.user.get_saved():
#        name = thread.url
#        logging.info('\tfollowing ' + name)
#        threads_to_follow.append(thread)
#    return threads_to_follow

def create_multi_reddit(followed_subreddits):
    return '+'.join(followed_subreddits)

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
          logging.debug(name + " detected in <" + text + ">")
          return name
          
    return None

def scan_for_messages(session):
    logging.debug("scanning for messages")
    unread = [message for message in session.get_unread() if message.was_comment == False 
                and message.subject in ('add trial', 'add recall')]
    for message in unread:
        time.sleep(2)
        author = str(message.author.name)
        subject = str(message.subject)
        body = str(message.body).replace('&amp;', '&')
        if(subject == "add recall"):
            type = 'recall'
            valid = body.startswith('https://secure.eveonline.com/RecallProgram/?invc=')
        else:
            type = 'trial'
            valid = body.startswith('https://secure.eveonline.com/trial/?invc=')
        
        if (not valid):
            message.reply('your link was invalid soz.')
            logging.info('discarded invalid ' + type + ' message from ' + author)
            message.mark_as_read()
            continue
        
        is_duplicate = [link for link in _links[type] if link['url'] == body or link['username'] == author]
        if (is_duplicate):
            message.reply('You already have a link. Get out.')
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


def scan_for_comments(session, followed_subreddits):
    comment_limit = 50
    my_subreddits = create_multi_reddit(followed_subreddits)
    #comments = praw.helpers.comment_stream(session, my_subreddits, 
    #                                            limit = comment_limit, verbosity = 0)
    comments = praw.helpers.submission_stream(session, my_subreddits, 
                                                limit = comment_limit, verbosity = 1)
    
    comment_count = 0   # Number of comments scanned (for logging)

    # Read each comment
    for scanning in comments:
        comment_count += 1
        index = str(comment_count)
        display_name = scanning.subreddit.display_name.lower()
        logging.debug('comment ' + index + ' from ' + display_name)
        text = None
        if hasattr(scanning, 'body'):
            text = scanning.body
        elif hasattr(scanning, 'selftext'):
            text = scanning.selftext
        else:
            logging.debug('skipping comment #' + index + ' because ' + str(type(scanning)))
            continue
        
        if is_probably_actionable(text):
            actionable = True
            # Check replies to see if already replied
            for reply in scanning.replies if hasattr(scanning, 'replies') else scanning.comments:
                if reply.author == None:
                    logging.debug("No author for comment #" + index)
                    actionable = False
                    break
                if reply.author.name == _username:
                    logging.debug("Already replied to comment #" + index)
                    actionable = False
                    break

            # If not already replied
            if (actionable == True):
                logging.debug("Actionable comment found at comment #" + index)
                post_reply(session, scanning, text)
                if (_enabled):
                    time.sleep(2)
                
        if (comment_count > comment_limit):
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
    provider = get_link_provider(link_type)
    response = 'Hi. I detected that you\'re looking for a ' + link_type +' link\n\n'
    response+= '/u/' + provider['username'] + ' has offered theirs:\n\n'
    response+= provider['url'] + '\n\nEnjoy!\n\n&nbsp;\n\n&nbsp;\n\n'
    

    if _enabled:
        display_name = thing.subreddit.display_name.lower()
        logging.info('('+display_name+') provided a ' + link_type + ' link')
        thing.reply(response + _signature)
    else:
        logging.info('disabled, but would have replied: ' + response)

# randomly find someone who offers that type of link
def get_link_provider(link_name):
    logging.debug(_config['links'])
    logging.debug(_config['links'].keys())
    link_key = [key for key in _config['links'].keys() if _config['links'][key]['name'] == link_name]
    for link in link_key:
        return random.choice(_links[link])
    
    return None # shouldn't happen

def get_tip_command(body):
    full_command_search_results = _regex_tip.search(body)
    if (full_command_search_results):
        return full_command_search_results.groups()[0]
    else:
        logging.info('could not find valid command in body')   
        return None 
    

def get_parent_author(r, thing):
    commentlinkid = thing.link_id[3:]
    parentid = thing.parent_id[3:]
    authorid = thing.author.name
    parentpermalink = thing.permalink.replace(thing.id, thing.parent_id[3:])

    if (commentlinkid==parentid):
        parentcomment = r.get_submission(parentpermalink)
    else:
        parentcomment = r.get_submission(parentpermalink).comments[0]
    
    if parentcomment.author == None:
        return None      
    else: 
        return parentcomment.author.name



def should_refresh_subreddits():
    return datetime.now() > _last_refreshed_subreddits + relativedelta(days = 1)


if __name__ == '__main__':
    main()
