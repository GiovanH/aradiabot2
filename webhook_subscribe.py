import os
from snip.stream import TriadLogger
# import tweepy
import time

from config import consumer_key, consumer_secret, access_token, access_token_secret, env_name
os.environ["consumer_key"] = consumer_key
os.environ["consumer_secret"] = consumer_secret
os.environ["access_token"] = access_token
os.environ["access_token_secret"] = access_token_secret
os.environ["env_name"] = env_name

import twitivity
logger = TriadLogger(__name__)


def refreshWebhook(callback_url, delay):
    os.environ["callback_url"] = callback_url  # Just in case

    # auth = tweepy.OAuthHandler(os.environ["consumer_key"], os.environ["consumer_secret"])
    # auth.set_access_token(os.environ["access_token"], os.environ["access_token_secret"])
    # api = tweepy.API(auth)
    # tweepy_my_id = api.me().id
    # logger.info(f"Logged into tweepy as {tweepy_my_id}")

    activity = twitivity.Activity()

    already_subscribed = activity.api(
        method="GET",
        endpoint=f"all/{os.environ['env_name']}/subscriptions.json"
    ).status_code == 204 

    if already_subscribed:
        # Delete old webhook
        import requests
        from config import bearer_token
        response = requests.get(
            f"https://api.twitter.com/1.1/account_activity/all/{os.environ['env_name']}/webhooks.json", 
            headers={"authorization": f"Bearer {bearer_token}"}
        )
        logger.info(f"{response}: {response.text}")
        response.raise_for_status()
        webhook_id = response.json()[0]["id"]
        webhook_url = response.json()[0]["url"]
        logger.info("Found old webhook with id " + webhook_id + " on url " + webhook_url)

        if webhook_url == callback_url and response.json()[0]["valid"]:
            logger.info("Old webhook still valid and correct.")
            return

        response = activity.api(
            method="DELETE",
            endpoint=f"all/{os.environ['env_name']}/webhooks/{webhook_id}.json"
        )
        # response = requests.get(
        #     f"https://api.twitter.com/1.1/account_activity/all/AAA/subscriptions/{webhook_id}.json", 
        #     headers={"authorization": f"Bearer {bearer_token}"}
        # )
        logger.info(f"{response}: {response.text}")
        response.raise_for_status()

    # Register new webhook
    if delay:
        logger.info(f"Pausing for {delay} secs to ensure server start")
        time.sleep(delay)

    logger.info(
        activity.register_webhook(
            callback_url=callback_url
        ).json()
    )
    logger.info(activity.subscribe().text)


if __name__ == "__main__":
    refreshWebhook(os.environ["callback_url"], 0)
