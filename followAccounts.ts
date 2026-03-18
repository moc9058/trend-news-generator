import 'dotenv/config';
import { Client, OAuth1, type OAuth1Config } from '@xdevplatform/xdk';

const oauth1Config: OAuth1Config = {
  apiKey: process.env.X_CONSUMER_KEY!,
  apiSecret: process.env.X_SECRET_KEY!,
  accessToken: process.env.X_ACCESS_TOKEN!,
  accessTokenSecret: process.env.X_ACCESS_TOKEN_SECRET!,
  callback: 'oob',
};

const oauth1 = new OAuth1(oauth1Config);
const client = new Client({ oauth1 });

const MY_USER_ID = '1826257844485955584';

const accounts = [
  'AndrewYNg',
  'ylecun',
  'kaborojevic',
  'GoogleDeepMind',
  'OpenAI',
  'huggingface',
  'kaggle',
  'weights_biases',
  'hardmaru',
  'ai_memes',
];

async function main(): Promise<void> {
  for (const username of accounts) {
    try {
      const userResponse = await client.users.getByUsername(username);

      if (!userResponse.data) {
        console.log(`[SKIP] @${username} — account not found`);
        continue;
      }

      const userId = userResponse.data.id;
      await client.users.followUser(MY_USER_ID, {
        body: { targetUserId: userId },
      });

      console.log(`[OK] Followed @${username} (${userId})`);
    } catch (error) {
      console.log(`[ERROR] @${username} — ${(error as Error).message}`);
    }
  }
}

main();
