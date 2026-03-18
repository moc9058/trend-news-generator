import 'dotenv/config';
import {
    Client,
    type ClientConfig,
    type Users
} from '@xdevplatform/xdk';

const config: ClientConfig = { bearerToken: process.env.X_BEARER_TOKEN! };

const client: Client = new Client(config);

async function main(): Promise<void> {
  const userResponse: Users.GetByUsernameResponse = await client.users.getByUsername('HyeongwooMOON');
  console.log(userResponse.data);
}

main();