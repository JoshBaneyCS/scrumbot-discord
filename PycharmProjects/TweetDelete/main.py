import tweepy
import time
from datetime import datetime
from typing import List, Set

# Twitter API credentials
BEARER_TOKEN = "YOUR_BEARER_TOKEN"
CONSUMER_KEY = "YOUR_CONSUMER_KEY"
CONSUMER_SECRET = "YOUR_CONSUMER_SECRET"
ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"
ACCESS_TOKEN_SECRET = "YOUR_ACCESS_TOKEN_SECRET"

# Configuration
PRESERVE_RETWEETS_FROM = [
    "username1",  # Add usernames without @ symbol
    "username2",
    "username3"
]

# Safety settings
DRY_RUN = True  # Set to False to actually delete tweets
RATE_LIMIT_DELAY = 1  # Seconds between deletions to avoid rate limits
MAX_TWEETS_TO_PROCESS = None  # Set a number to limit processing (None = all tweets)


class TwitterCleaner:
    def __init__(self):
        """Initialize Twitter API client"""
        self.client = tweepy.Client(
            bearer_token=BEARER_TOKEN,
            consumer_key=CONSUMER_KEY,
            consumer_secret=CONSUMER_SECRET,
            access_token=ACCESS_TOKEN,
            access_token_secret=ACCESS_TOKEN_SECRET,
            wait_on_rate_limit=True
        )

        # Get authenticated user info
        self.me = self.client.get_me()
        if self.me.data:
            self.user_id = self.me.data.id
            self.username = self.me.data.username
            print(f"Authenticated as @{self.username} (ID: {self.user_id})")
        else:
            raise Exception("Failed to authenticate")

    def get_user_ids_to_preserve(self) -> Set[str]:
        """Convert usernames to user IDs for accounts whose retweets we want to preserve"""
        user_ids = set()

        for username in PRESERVE_RETWEETS_FROM:
            try:
                user = self.client.get_user(username=username)
                if user.data:
                    user_ids.add(str(user.data.id))
                    print(f"Will preserve retweets from @{username} (ID: {user.data.id})")
                else:
                    print(f"Warning: Could not find user @{username}")
            except Exception as e:
                print(f"Error looking up @{username}: {e}")

        return user_ids

    def get_all_tweets(self) -> List[dict]:
        """Fetch all tweets from the authenticated user"""
        all_tweets = []
        pagination_token = None

        print(f"\nFetching tweets from @{self.username}...")

        while True:
            try:
                # Get tweets with necessary fields
                tweets = self.client.get_users_tweets(
                    id=self.user_id,
                    max_results=100,  # Maximum allowed per request
                    pagination_token=pagination_token,
                    tweet_fields=['created_at', 'referenced_tweets', 'author_id'],
                    expansions=['referenced_tweets.id.author_id']
                )

                if tweets.data:
                    for tweet in tweets.data:
                        tweet_dict = {
                            'id': tweet.id,
                            'text': tweet.text,
                            'created_at': tweet.created_at,
                            'referenced_tweets': tweet.referenced_tweets
                        }

                        # Add author info for referenced tweets if available
                        if tweets.includes and 'tweets' in tweets.includes:
                            for ref_tweet in tweets.includes['tweets']:
                                tweet_dict[f'ref_tweet_{ref_tweet.id}_author'] = ref_tweet.author_id

                        all_tweets.append(tweet_dict)

                    print(f"Fetched {len(all_tweets)} tweets so far...")

                # Check for more pages
                if tweets.meta and 'next_token' in tweets.meta:
                    pagination_token = tweets.meta['next_token']
                else:
                    break

                # Respect rate limits
                time.sleep(0.5)

            except Exception as e:
                print(f"Error fetching tweets: {e}")
                break

        print(f"Total tweets fetched: {len(all_tweets)}")
        return all_tweets

    def should_delete_tweet(self, tweet: dict, preserve_user_ids: Set[str]) -> bool:
        """Determine if a tweet should be deleted"""
        # Check if it's a retweet
        if tweet.get('referenced_tweets'):
            for ref in tweet['referenced_tweets']:
                if ref.type == 'retweeted':
                    # Get the original tweet's author ID
                    ref_tweet_id = ref.id
                    author_key = f'ref_tweet_{ref_tweet_id}_author'

                    # If we have author info and it's in our preserve list, don't delete
                    if author_key in tweet:
                        author_id = str(tweet[author_key])
                        if author_id in preserve_user_ids:
                            return False  # Don't delete - it's a retweet from preserved account

        # Delete all other tweets (including retweets from non-preserved accounts)
        return True

    def delete_tweets(self, tweets_to_delete: List[dict]):
        """Delete the specified tweets"""
        deleted_count = 0
        failed_count = 0

        for i, tweet in enumerate(tweets_to_delete):
            if MAX_TWEETS_TO_PROCESS and i >= MAX_TWEETS_TO_PROCESS:
                print(f"\nReached maximum tweet limit ({MAX_TWEETS_TO_PROCESS})")
                break

            tweet_id = tweet['id']
            tweet_preview = tweet['text'][:50] + '...' if len(tweet['text']) > 50 else tweet['text']

            if DRY_RUN:
                print(f"[DRY RUN] Would delete tweet {tweet_id}: {tweet_preview}")
                deleted_count += 1
            else:
                try:
                    self.client.delete_tweet(tweet_id)
                    print(f"Deleted tweet {tweet_id}: {tweet_preview}")
                    deleted_count += 1

                    # Rate limit protection
                    time.sleep(RATE_LIMIT_DELAY)

                except Exception as e:
                    print(f"Failed to delete tweet {tweet_id}: {e}")
                    failed_count += 1

        return deleted_count, failed_count

    def run(self):
        """Main execution method"""
        print("\n" + "=" * 50)
        print("TWITTER/X CLEANUP SCRIPT")
        print("=" * 50)

        if DRY_RUN:
            print("\n⚠️  DRY RUN MODE - No tweets will actually be deleted")
            print("Set DRY_RUN = False to perform actual deletions\n")
        else:
            print("\n⚠️  WARNING: This will DELETE tweets permanently!")
            confirm = input("Type 'DELETE' to confirm: ")
            if confirm != 'DELETE':
                print("Aborted.")
                return

        # Get user IDs for preserved accounts
        preserve_user_ids = self.get_user_ids_to_preserve()

        # Fetch all tweets
        all_tweets = self.get_all_tweets()

        if not all_tweets:
            print("No tweets found.")
            return

        # Filter tweets to delete
        tweets_to_delete = []
        tweets_to_keep = []

        for tweet in all_tweets:
            if self.should_delete_tweet(tweet, preserve_user_ids):
                tweets_to_delete.append(tweet)
            else:
                tweets_to_keep.append(tweet)

        # Summary
        print("\n" + "=" * 50)
        print("SUMMARY")
        print("=" * 50)
        print(f"Total tweets found: {len(all_tweets)}")
        print(f"Tweets to DELETE: {len(tweets_to_delete)}")
        print(f"Retweets to KEEP: {len(tweets_to_keep)}")

        if tweets_to_keep:
            print("\nPreserved retweets preview:")
            for tweet in tweets_to_keep[:5]:  # Show first 5
                preview = tweet['text'][:60] + '...' if len(tweet['text']) > 60 else tweet['text']
                print(f"  - {preview}")
            if len(tweets_to_keep) > 5:
                print(f"  ... and {len(tweets_to_keep) - 5} more")

        if not tweets_to_delete:
            print("\nNo tweets to delete!")
            return

        print("\n" + "=" * 50)

        # Proceed with deletion
        if DRY_RUN:
            print("Starting DRY RUN deletion process...")
        else:
            print("Starting ACTUAL deletion process...")
            print("You can stop the script at any time with Ctrl+C")

        deleted, failed = self.delete_tweets(tweets_to_delete)

        # Final report
        print("\n" + "=" * 50)
        print("COMPLETED")
        print("=" * 50)
        if DRY_RUN:
            print(f"DRY RUN: Would have deleted {deleted} tweets")
        else:
            print(f"Successfully deleted: {deleted} tweets")
            if failed > 0:
                print(f"Failed to delete: {failed} tweets")
        print(f"Preserved retweets: {len(tweets_to_keep)}")


if __name__ == "__main__":
    try:
        cleaner = TwitterCleaner()
        cleaner.run()
    except KeyboardInterrupt:
        print("\n\nScript interrupted by user.")
    except Exception as e:
        print(f"\nError: {e}")
        print("\nMake sure you have:")
        print("1. Installed tweepy: pip install tweepy")
        print("2. Set up your Twitter API credentials")
        print("3. Enabled OAuth 1.0a with read and write permissions")