import os
import json
import tweepy
import re
from snip.stream import TriadLogger

import requests
import snip.net
import subprocess
from threading import Lock
from stream_config import *

import threading

from config import consumer_key, consumer_secret, access_token, access_token_secret
os.environ["consumer_key"] = consumer_key
os.environ["consumer_secret"] = consumer_secret
os.environ["access_token"] = access_token
os.environ["access_token_secret"] = access_token_secret
os.environ["env_name"] = "AAA"
os.environ["callback_url"] = callback_url

import twitivity

logger = TriadLogger(__name__)


HELP_DOC = """Valid commands:
RETWEET|RT {tweetlink}
TWEET|SEND {Text}
REPLY|THREAD {Text} {tweetlink}
CONVERT|SCALE {x}:{y} [bg]
If signature not in tweet, it will be added
A tweetlink can be a full link to a tweet, or a "share"
| signifies "or"; so "REWEET" or "RT" are the same
"""


# Api override: Allow the use of quick reply options
def send_direct_message2(self, recipient_id, text, quick_reply_options=None, attachment_type=None, attachment_media_id=None):
    """ Send a direct message to the specified user from the authenticating user """
    json_payload = {'event': {'type': 'message_create', 'message_create': {'target': {'recipient_id': recipient_id}}}}
    json_payload['event']['message_create']['message_data'] = {'text': text}
    if quick_reply_options is not None:
        json_payload['event']['message_create']['message_data']['quick_reply'] = {'type': "options", 'options': [{"label": option} for option in quick_reply_options]}

    if attachment_type is not None and attachment_media_id is not None:
        json_payload['event']['message_create']['message_data']['attachment'] = {'type': attachment_type}
        json_payload['event']['message_create']['message_data']['attachment']['media'] = {'id': attachment_media_id}

    try:
        with open("lastsentpayload.json", "w") as fp:
            json.dump(json_payload, fp, indent=2)
    except TypeError:
        pass

    return self._send_direct_message(json_payload=json_payload)


def getTweetIdFromUrl(url):
    match = re.search(r"^https:\/\/twitter\.com\/(\w+)\/status\/(\d+)(\?.*)*$", url)
    if match:
        (user, tweetid, *_) = match.groups()
        return (user, tweetid)
    else:
        return None


def url_params(url: str) -> str:
    pattern: str = r"^[^\/]+:\/\/[^\/]*?\.?([^\/.]+)\.[^\/.]+(?::\d+)?\/"
    return re.split(pattern=pattern, string=url)[-1]


class StreamEvent(twitivity.Event):
    CALLBACK_URL: str = os.environ["callback_url"]

    def __init__(self, api):
        super().__init__()
        self.api = api
        self.me = api.me()
        self.fslock = Lock()
        for screen_name in whitelist_recognize_dm_commands:
            self.api.create_friendship(screen_name=screen_name)

    def on_data(self, data: json) -> None:
        if data.get("direct_message_events"):
            self.on_direct_message(data)
        else:
            logger.info(f"Don't care about {data.keys()}")

    def dmRespond(self, sender_id, string, screen_name=None, **kwargs):
        if not screen_name:
            screen_name = sender_id
        logger.info(f"'{repr(string)}' -> {screen_name}")
        send_direct_message2(api, sender_id, string, **kwargs)

    def sendHelp(self, sender):
        self.dmRespond(sender.id, HELP_DOC)

    def on_direct_message(self, data):
        for event in data.get("direct_message_events"):
            if event.get("type") == "message_create":
                sender_id = event["message_create"]["sender_id"]

                if str(sender_id) == str(self.me.id):
                    return

                sender = self.api.get_user(user_id=sender_id)
                logger.info("Got DM from User @" + sender.screen_name + f" ({sender_id})")

                # Dump data
                with open("lastdm.json", "w") as fp:
                    json.dump(data, fp, indent=2)

                if sender.screen_name.lower() in whitelist_recognize_dm_commands:
                    # Process any commands
                    command = event["message_create"]["message_data"].get("text", "").split(" ")[0]
                    if command.upper() == "HELP":
                        self.sendHelp(sender)
                    elif command.upper() == "RETWEET" or command.upper() == "RT":
                        self.tryRetweetFwds(sender, event)
                    elif command.upper() == "TWEET" or command.upper() == "SEND":
                        self.trySendTweet(sender, event)
                    elif command.upper() == "REPLY" or command.upper() == "THREAD":
                        self.trySendThread(sender, event)
                    elif command.upper() == "CONVERT" or command.upper() == "SCALE":
                        self.tryConvertMedia(sender, event)
                    else:
                        self.dmRespond(
                            sender_id, f"Error: unknown command: '{command}'",
                            screen_name=sender.screen_name,
                            quick_reply_options=["Help"],
                        )
                else:
                    logger.info(f"User screen name {sender.screen_name} not in whitelist {whitelist_recognize_dm_commands}")

    def tryRetweetFwds(self, sender, event):
        if sender.screen_name.lower() not in whitelist_dm_retweet:
            logger.info("User @" + sender.screen_name + f" is not on whitelist {whitelist_dm_retweet}.")
            return
        else:
            logger.info("Scanning @" + sender.screen_name + "'s DM for tweets'")

        attached_urls = event["message_create"]["message_data"]["entities"]["urls"]
        if not attached_urls:
            self.dmRespond(sender.id, "Error: You must attach a tweet to retweet!")
            return
        for url in attached_urls:
            expanded_url = url["expanded_url"]
            logger.info(f"Found url '{expanded_url}")
            fwd_tweet_data = getTweetIdFromUrl(expanded_url)
            if fwd_tweet_data:
                (fwd_tweet_author, fwd_tweet_id) = fwd_tweet_data
                logger.info(f"Retweeting forwarded tweet {fwd_tweet_id} from {fwd_tweet_author}")
                self.api.retweet(fwd_tweet_id)

    def trySendTweet(self, sender, event):
        if sender.screen_name.lower() not in whitelist_dm_sendtweet:
            logger.info("User @" + sender.screen_name + f" is not on whitelist {whitelist_dm_sendtweet}.")
            return

        message = " ".join(event["message_create"]["message_data"].get("text", "").split(" ")[1:])
        self._trySendTweet(sender, message)

    def _trySendTweet(self, sender, message, **kwargs):
        if not message:
            self.dmRespond(sender.id, "Error: Your tweet must include a message")
            return

        signature = authors.get(sender.screen_name.lower())
        if signature not in message:
            message = f"{message} -{signature}"

        try:
            logger.info(f"Tweeting '{message}' ({kwargs})")
            new_status = self.api.update_status(message, **kwargs)
            self.dmRespond(sender.id, f"Sent tweet https://twitter.com/{self.me.screen_name}/status/{new_status.id}", sender.screen_name)

            with open("lastsenttweet.json", "w") as fp:
                json.dump(new_status._json, fp, indent=2)

        except tweepy.error.TweepError as e:
            self.dmRespond(sender.id, f"Error from twitter: {e}", sender.screen_name)

    def trySendThread(self, sender, event):
        if sender.screen_name.lower() not in whitelist_dm_sendtweet:
            logger.info("User @" + sender.screen_name + f" is not on whitelist {whitelist_dm_sendtweet}.")
            return
        else:
            logger.info("Scanning @" + sender.screen_name + "'s DM for tweets'")

        replying_to_id = None
        attached_urls = event["message_create"]["message_data"]["entities"]["urls"]
        for url in attached_urls:
            expanded_url = url["expanded_url"]
            short_url = url["url"]
            logger.info(f"Found url '{expanded_url}")
            fwd_tweet_data = getTweetIdFromUrl(expanded_url)
            if fwd_tweet_data:
                (fwd_tweet_author, replying_to_id) = fwd_tweet_data
                logger.info(f"Setting reply tweet to {replying_to_id} from {fwd_tweet_author}")

        if replying_to_id:
            message = " ".join(event["message_create"]["message_data"].get("text", "").split(" ")[1:])
            logger.info(f"Message set to '{message}'")

            message = re.sub(rf"\s*({short_url}|{expanded_url})", "", message)
            logger.info(f"Message set to '{message}'")
            # message = f"@{fwd_tweet_author} {message}"
            # logger.info(f"Message set to '{message}'")

            self._trySendTweet(
                sender, message,
                in_reply_to_status_id=int(replying_to_id),
                in_reply_to_user_id=api.get_user(screen_name=fwd_tweet_author).id
            )
        else:
            self.dmRespond(sender.id, f"Could not find the tweet to reply to. Make sure you attached it.", sender.screen_name)

    def tryConvertMedia(self, sender, event):
        if sender.screen_name.lower() not in whitelist_dm_convert:
            logger.info("User @" + sender.screen_name + f" is not on whitelist {whitelist_dm_retweet}.")
            return

        try:
            attachment = event["message_create"]["message_data"]["attachment"]
        except KeyError:
            self.dmRespond(sender.id, "Error: You must attach a picture to convert!")
            return

        try:
            resolution = event["message_create"]["message_data"].get("text", "").split(" ")[1]
            resolutionx, resolutiony = resolution.split(":")
            map(int, resolution.split(":"))  # Assert valid ints
            logger.info(f"Desired aspect ratio {resolutionx}x{resolutiony}")
        except (KeyError, ValueError):
            self.dmRespond(sender.id, "Error: You must include an aspect ratio.\nCommon twitter aspect ratios are:\n16:9 (Single photo)\n7:8 (Side photo)\n7:4 (Corner photo)")
            return

        attachment_url = attachment["media"]["media_url"]
        logger.info(f"Got image {attachment_url} from @{sender.screen_name}")

        imagestream = requests.get(
            attachment_url,
            auth=self.api.auth.apply_auth()
        )

        with self.fslock:
            snip.net.saveStreamAs(imagestream, "twitter_in/auto.jpg")
            subprocess.run(["bash", "./format_for_twitter.sh", resolutionx, resolutiony])
            media_id = self.api.media_upload(f"twitter_out/auto.{resolutionx}x{resolutiony}.jpg").media_id
        self.api.send_direct_message(sender.id, None, attachment_type="media", attachment_media_id=media_id)


if __name__ == "__main__":
    from webhook_subscribe import refreshWebhook

    auth = tweepy.OAuthHandler(os.environ["consumer_key"], os.environ["consumer_secret"])
    auth.set_access_token(os.environ["access_token"], os.environ["access_token_secret"])
    api = tweepy.API(auth)
    logger.info(f"Logged into tweepy as {api.me().name}")

    # stream_event = StreamEvent(api)
    # logger.info(f"Listening to streamer {stream_event} on url {stream_event.CALLBACK_URL}")
    # threading.Thread(target=stream_event.listen).start()

    # logger.info(f"Queueing webhook refresh process")
    # threading.Thread(target=refreshWebhook, args=(os.environ["callback_url"],)).start()

    logger.info(f"Queueing webhook refresh process")
    threading.Thread(target=refreshWebhook, args=(os.environ["callback_url"], 2)).start()

    stream_event = StreamEvent(api)
    logger.info(f"Listening to streamer {stream_event} on url {stream_event.CALLBACK_URL}")
    stream_event.listen()

    # logger.info(f"Pausing main thread")
    # signal.pause()
