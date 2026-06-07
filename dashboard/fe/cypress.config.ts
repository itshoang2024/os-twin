import { defineConfig } from 'cypress';

export default defineConfig({
  e2e: {
    baseUrl: 'http://127.0.0.1:3050',
    specPattern: 'cypress/e2e/**/*.cy.{ts,tsx,js,jsx}',
    supportFile: false,
    video: false,
    screenshotOnRunFailure: true,
  },
});
