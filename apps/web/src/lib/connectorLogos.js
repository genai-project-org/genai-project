// Brand logos for the Connectors list: simple-icons slug + brand colour per connector id.
// Icons are served from the simple-icons package on jsDelivr; anything missing (or a failed
// load) falls back to a coloured initial in the UI.
export const ICON_CDN = 'https://cdn.jsdelivr.net/npm/simple-icons/icons';

const L = {
  google_calendar: ['googlecalendar', '4285F4'],
  gmail: ['gmail', 'EA4335'],
  google_docs: ['googledocs', '4285F4'],
  google_sheets: ['googlesheets', '34A853'],
  google_drive: ['googledrive', '4285F4'],
  gcp: ['googlecloud', '4285F4'],
  google_analytics: ['googleanalytics', 'E37400'],
  github: ['github', '181717'],
  gitlab: ['gitlab', 'FC6D26'],
  bitbucket: ['bitbucket', '0052CC'],
  slack: ['slack', '4A154B'],
  notion: ['notion', '000000'],
  atlassian_jira: ['jira', '0052CC'],
  atlassian_confluence: ['confluence', '172B4D'],
  microsoft_teams: ['microsoftteams', '6264A7'],
  microsoft_outlook_mail: ['microsoftoutlook', '0078D4'],
  microsoft_onedrive: ['microsoftonedrive', '0078D4'],
  microsoft_sharepoint: ['microsoftsharepoint', '0078D4'],
  azure: ['microsoftazure', '0078D4'],
  dropbox: ['dropbox', '0061FF'],
  box: ['box', '0061D5'],
  asana: ['asana', 'F06A6A'],
  linear: ['linear', '5E6AD2'],
  clickup: ['clickup', '7B68EE'],
  basecamp: ['basecamp', '1D2D35'],
  airtable: ['airtable', '18BFFF'],
  trello: ['trello', '0052CC'],
  sentry: ['sentry', '362D59'],
  hubspot: ['hubspot', 'FF7A59'],
  salesforce: ['salesforce', '00A1E0'],
  intercom: ['intercom', '6AFDEF'],
  zendesk: ['zendesk', '03363D'],
  mailchimp: ['mailchimp', 'FFE01B'],
  sendgrid: ['sendgrid', '1A82E2'],
  docusign: ['docusign', 'FFCC22'],
  stripe: ['stripe', '635BFF'],
  paypal: ['paypal', '003087'],
  shopify: ['shopify', '7AB55C'],
  quickbooks: ['quickbooks', '2CA01C'],
  twitter_x: ['x', '000000'],
  reddit: ['reddit', 'FF4500'],
  linkedin: ['linkedin', '0A66C2'],
  discord: ['discord', '5865F2'],
  zoom: ['zoom', '0B5CFF'],
  telegram: ['telegram', '26A5E4'],
  twilio: ['twilio', 'F22F46'],
  whatsapp_business: ['whatsapp', '25D366'],
  vercel: ['vercel', '000000'],
  aws: ['amazonwebservices', 'FF9900'],
  circleci: ['circleci', '343434'],
};

export function logoFor(id) {
  const entry = L[id];
  if (!entry) return null;
  const [slug, hex] = entry;
  return { url: `${ICON_CDN}/${slug}.svg`, hex };
}

// Near-black brand colours disappear on dark backgrounds; those use the theme foreground instead.
export function isDarkHex(hex) {
  const n = parseInt(hex, 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.28;
}
