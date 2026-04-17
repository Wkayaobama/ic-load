/**
 * Create a simple HubSpot form in sandbox.
 *
 * Usage (PowerShell):
 *   $env:HUBSPOT_SANDBOX_TOKEN="pat-..."
 *   node .\hubspotscripts-master\form_updates\create-form.js 49610528
 */

const portalId = process.argv[2];
const token = process.env.HUBSPOT_SANDBOX_TOKEN || process.env.HUBSPOT_ACCESS_TOKEN;

if (!portalId) {
  console.error("Usage: node create-form.js <portalId>");
  process.exit(1);
}

if (!token) {
  console.error("Set HUBSPOT_SANDBOX_TOKEN or HUBSPOT_ACCESS_TOKEN first.");
  process.exit(1);
}

const readline = require("readline");

async function confirm() {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  const answer = await new Promise((resolve) =>
    rl.question(`This will CREATE a new HubSpot form in portal ${portalId}. Type YES to continue: `, resolve)
  );
  rl.close();
  if (String(answer).trim() !== "YES") {
    console.error("Aborted by user (confirmation not provided).");
    process.exit(1);
  }
}

const now = new Date().toISOString().replace(/[:.]/g, "-");
const payload = {
  name: `Sandbox Simple Form ${now}`,
  submitText: "Submit",
  notifyRecipients: "",
  formFieldGroups: [
    {
      fields: [
        { name: "firstname", label: "First name", type: "string", fieldType: "text", required: false },
        { name: "lastname", label: "Last name", type: "string", fieldType: "text", required: false },
        { name: "email", label: "Email", type: "string", fieldType: "text", required: true }
      ]
    }
  ]
};

async function run() {
  await confirm();
  const response = await fetch(`https://api.hubapi.com/forms/v2/forms?portalId=${portalId}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });

  const data = await response.json();
  if (!response.ok) {
    console.error("Form creation failed:", JSON.stringify(data, null, 2));
    process.exit(1);
  }

  console.log("Form created successfully:");
  console.log(JSON.stringify({
    guid: data.guid,
    name: data.name,
    portalId: data.portalId
  }, null, 2));
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
