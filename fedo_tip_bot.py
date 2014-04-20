import praw             
import sys              
import time             
import logging
import warnings
import yaml
import re
from decimal    import Decimal
from datetime   import datetime
from dateutil.relativedelta import relativedelta

logging.basicConfig(format='%(asctime)s %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S',
                    level=logging.INFO)
requests_log = logging.getLogger("requests")
requests_log.setLevel(logging.WARNING)
_sleeptime = 60

def readYamlFile(path):
    with open(path, 'r') as infile:
        return yaml.load(infile)

_config_file_name = 'fedo_tip_bot_config.yaml'
_config = readYamlFile(_config_file_name)
_api_header = _config['api_header']
_username = _config['username']
_password = _config['password']
_enabled = _config['enabled']
_sleeptime = _config['sleep_time']
_signature = _config['signature']
_last_refreshed_subreddits = datetime.now() + relativedelta( days = -2 )

_regex_start_string = "(\\+(fedo_tip|fedotip|fedo_tip_bot)"
_regex_redditusername_string ="(\\s(((@)?([A-Za-z0-9_-]{3,20}))))?)"
_regex_currencyamount_string = "(\\s((\\s?((\\d|\\,){0,10}(\\d\\.?|\\.(\\d|\\,){0,10}))"
_regex_currencycode_only_string = "(\\s?(FED(O)?|fedo)(s)?)"
_regex_currencycode_string = _regex_currencycode_only_string + "?)))"
_regex_verification_string = "(\\s(NOVERIFY|VERIFY))?"

_regex_tip_string = ('(' + _regex_start_string + _regex_redditusername_string 
    + _regex_currencyamount_string + _regex_currencycode_string 
    + _regex_verification_string + ')')

_regex_redditusername = re.compile(_regex_start_string+_regex_redditusername_string,re.IGNORECASE)
_regex_currency = re.compile(_regex_currencyamount_string+_regex_currencycode_string,re.IGNORECASE)
_regex_currency_only = re.compile(_regex_currencycode_only_string,re.IGNORECASE)
_regex_verification = re.compile(_regex_verification_string,re.IGNORECASE)
_regex_tip = re.compile(_regex_tip_string,re.IGNORECASE)

currencies = { 
    ('fed','fedo','fedos'): 'Fedo', 
}

working_currencies = {}
for k, v in currencies.items():
    for key in k:
        working_currencies[key] = v
    

def main():
    global _last_refreshed_subreddits
    sleeptime = _sleeptime
    r = praw.Reddit(_api_header)
    r.login(_username, _password)
    logging.info('Logged into reddit as ' + _username)
    
    while(True):
        try:
            if (should_refresh_subreddits()):
                followed_subreddits = get_subreddits_to_follow(r)
                _last_refreshed_subreddits = datetime.now()
            
            scan_for_comments(r, followed_subreddits)
            
            if (sleeptime > (_sleeptime)):
                sleeptime = round(sleeptime/2)
        
        except Exception as e:
            #exponential sleeptime back-off
            #if not successful, slow down.
            
            catchable_exceptions = ["Gateway Time", "timed out", "HTTPSConnectionPool", "Connection reset"]
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
        subreddits_to_follow.append(subreddit.display_name.lower())
    return subreddits_to_follow
    
def create_multi_reddit(followed_subreddits):
    return '+'.join(followed_subreddits)

# exit hook
def exitexception(e):
     #TODO re-add if required
     #print ("Error ", str(e))
     #exit(1)
     raise

def is_probably_actionable(thing):
    tip_command_keyword = _regex_redditusername.search(thing.body)
    if (not tip_command_keyword):
        return False
    # TODO add disallowed user names here if required
    return True

def scan_for_comments(session, followed_subreddits):
    comment_limit = 1000
    my_subreddits = create_multi_reddit(followed_subreddits)
    comments = praw.helpers.comment_stream(session, my_subreddits, 
                                                limit = comment_limit, verbosity = 0)
    comment_count = 0   # Number of comments scanned (for logging)

    # Read each comment
    for scanning in comments:
        comment_count += 1
        index = str(comment_count)
        display_name = scanning.subreddit.display_name.lower()
        logging.debug('comment ' + index + ' from ' + display_name)
        if not hasattr(scanning, 'body'):
            logging.debug('skipping comment #' + index + ' because ' + str(type(scanning)))
            continue
        
        if is_probably_actionable(scanning):
            actionable = True
            # Check replies to see if already replied
            for reply in scanning.replies:
                if reply.author.name == _username:
                    logging.debug("Already replied to comment #" + index)
                    actionable = False
                    break

            # If not already replied
            if (actionable == True):
                logging.debug("Actionable comment found at comment #" + index)
                post_reply(session, scanning)
                if (_enabled):
                    break
                
        if (comment_count > comment_limit):
            #Reddit API is being too generous; quit early, go home, play with the kids
            logging.debug('reached limit, breaking off')
            break

def post_reply(r, thing):      
    tip_command = get_tip_command(thing.body)
    if (tip_command is None):
        # shouldn't, but regex mistakes do happen
        return

    from_redditor = thing.author.name
    to_redditor = get_to_redditor(tip_command, get_parent_author(r, thing)) 
    
    currency_results = _regex_currency.search(tip_command)
    amount = ''.join(c for c in currency_results.groups()[0] if c.isdigit() or c in (',','.'))
    
    currency_code_only = _regex_currency_only.search(tip_command)
    code = normalise(currency_code_only.groups()[1])
    
    
    if (Decimal(amount) > 1):
        code = code + 's'
    first_line = 'Transaction Verified!\n\n**'
    second_line = from_redditor + ' --> '
    second_line+= amount + ' ' + code + ' --> '
    second_line+= to_redditor
    
    response = first_line + second_line + '**\n\n'
    if _enabled:
        display_name = scanning.subreddit.display_name.lower()
        logging.info('('+display_name+') ' + second_line)
        thing.reply(response + _signature)
    else:
        logging.info('disabled, but would have replied: ' + second_line)

def normalise(currency_code):
    return working_currencies[currency_code.lower()]

def get_to_redditor(tip_command, default_value):
    username_results = _regex_redditusername.search(tip_command)
    if (username_results.groups()[3] is not None):
        return username_results.groups()[3]
    else:
        return default_value

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
            
    return parentcomment.author.name



def should_refresh_subreddits():
    return datetime.now() > _last_refreshed_subreddits + relativedelta(days = 1)


if __name__ == '__main__':
    main()
