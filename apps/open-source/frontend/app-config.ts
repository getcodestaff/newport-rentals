import type { AppConfig } from './lib/types';

export const APP_CONFIG_DEFAULTS: AppConfig = {
  companyName: 'Voice Sell AI',
  pageTitle: 'Voice Sell AI - Your #1 AI Customer Support and AI Sales Company',
  pageDescription: 'Voice Sell AI Your #1 AI Customer Support and AI Sales Company',

  supportsChatInput: true,
  supportsVideoInput: true,
  supportsScreenShare: true,
  isPreConnectBufferEnabled: false,

  logo: '/voice-sell-logo.png',
  accent: '#3b82f6',
  logoDark: '/voice-sell-logo.png',
  accentDark: '#60a5fa',
  startButtonText: 'Start Booking Call',
};
