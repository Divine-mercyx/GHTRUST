// Build-time checks on top of app.json (Expo passes app.json in as `config`).
//
// A release build without EXPO_PUBLIC_API_URL would fall back to the development
// origin (http://<metro host>:8000) and reach nothing, so the build fails instead.
const fs = require('fs');
const path = require('path');

const RELEASE_PROFILES = ['preview', 'production'];

// Android push needs Firebase's google-services.json. On EAS it comes from a "file"
// environment variable (GOOGLE_SERVICES_JSON holds the path on the build machine);
// locally, from mobile/google-services.json. Without it the app builds and in-app
// notifications work, but Android phones get no push notifications.
function googleServicesFile() {
  if (process.env.GOOGLE_SERVICES_JSON) return process.env.GOOGLE_SERVICES_JSON;
  const local = path.join(__dirname, 'google-services.json');
  return fs.existsSync(local) ? './google-services.json' : undefined;
}

module.exports = ({ config }) => {
  const profile = process.env.EAS_BUILD_PROFILE;
  if (RELEASE_PROFILES.includes(profile)) {
    const apiUrl = process.env.EXPO_PUBLIC_API_URL;
    if (!apiUrl) {
      throw new Error(`EXPO_PUBLIC_API_URL must be set for the "${profile}" build (see mobile/.env.example).`);
    }
    if (profile === 'production' && !apiUrl.startsWith('https://')) {
      throw new Error(`EXPO_PUBLIC_API_URL must use https:// for production builds (got ${apiUrl}).`);
    }
    // A tester or store build pointed at someone's laptop or LAN reaches nobody else.
    const host = apiUrl.replace(/^https?:\/\//, '').split(/[/:]/)[0];
    if (/^(localhost$|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host)) {
      throw new Error(`EXPO_PUBLIC_API_URL points at a local network address (${host}) in the "${profile}" build.`);
    }
    if (profile === 'production' && !process.env.EXPO_PUBLIC_ANDROID_STORE_URL) {
      throw new Error('EXPO_PUBLIC_ANDROID_STORE_URL must be set for production (the forced-update screen links to it).');
    }
  }
  const firebase = googleServicesFile();
  if (firebase) config.android = { ...config.android, googleServicesFile: firebase };
  return config;
};
