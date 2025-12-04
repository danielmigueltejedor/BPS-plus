// BPS-Plus generated script

const BASE_URL = "__BASE_URL__";
const TOKEN = "__TOKEN__";
const UPDATE_INTERVAL = __UPDATE_INTERVAL__; // ms

async function getBpsPlusData() {
  try {
    const r = await fetch(`${BASE_URL}/api/states`, {
      headers: {
        Authorization: `Bearer ${TOKEN}`,
        "Content-Type": "application/json",
      },
    });

    if (!r.ok) {
      console.error("BPS-Plus error:", r.status);
      return;
    }

    const data = await r.json();

    const entities = data.filter(e => e.entity_id.includes("_distance_to_"));
    console.log("BPS-Plus entities:", entities);

    // << AQUI PINTAS TU MAPA >>
  } catch (err) {
    console.error("BPS-Plus JS Error:", err);
  }
}

setInterval(getBpsPlusData, UPDATE_INTERVAL);
getBpsPlusData();
