// Runs only for a newly initialized volume. Never resets an existing database.
const database = db.getSiblingDB('kb_stage1');
database.createUser({
  user: 'kb_app',
  pwd: process.env.MONGO_APP_PASSWORD,
  roles: [{ role: 'readWrite', db: 'kb_stage1' }],
});
