//Create a long-lived token
//Click on you user in the bottom left corner
//Click on security on the top of the page
//In the bottom of the page, create a new token. The name does not matter
//Copy the token and below
//Example: const hass_token = "my_secret_token";
const hass_token = "";
// Add your url that you use in your browser
//Example1: const hassURL = "xxx.duckdns.org";
//Example2: const hassURL = "192.168.0.10:8123";
const hassURL = "";

document.addEventListener('DOMContentLoaded', async () => {
    const canvas = document.getElementById('canvas');
    const ctx = canvas.getContext('2d');
    const upload = document.getElementById('upload');
    const mapSelector = document.getElementById('mapSelector');
    const entSelector = document.getElementById('entSelector');
    const mapbuttondiv = document.getElementById('mapbuttondiv');
    const savebuttondiv = document.getElementById('savebuttondiv');
    const trackdiv = document.getElementById('trackdiv');
    const zonediv = document.getElementById('zonediv');
    const messdiv = document.getElementById('message');
    const calReceiverSelect = document.getElementById('calReceiver');
    const calFactorInput = document.getElementById('calFactor');
    const calOffsetInput = document.getElementById('calOffset');
    const calSaveManualButton = document.getElementById('calSaveManual');
    const calEntitySelect = document.getElementById('calEntity');
    const calMeasuredMetersInput = document.getElementById('calMeasuredMeters');
    const calCaptureSampleButton = document.getElementById('calCaptureSample');
    const calComputeAutoButton = document.getElementById('calComputeAuto');
    const calStatus = document.getElementById('calStatus');
    const wallPenaltyInput = document.getElementById('wallPenalty');
    const wallPenaltySaveButton = document.getElementById('wallPenaltySave');
    const wallPenaltyPresetSelect = document.getElementById('wallPenaltyPreset');
    const calProPickPositionButton = document.getElementById('calProPickPosition');
    const calProAutoButton = document.getElementById('calProAuto');
    const calProStatus = document.getElementById('calProStatus');
    const saveButton = document.createElement('button');

    //Delete button
    const deleteButton = document.createElement('button');
    deleteButton.className = 'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&amp;_svg]:pointer-events-none [&amp;_svg]:size-4 [&amp;_svg]:shrink-0 text-primary-foreground hover:bg-primary/90 h-10 px-4 py-2';
    deleteButton.style = 'background-color: red';
    deleteButton.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-save w-4 h-4 mr-2" data-component-name="Save"><path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"></path><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"></path><path d="M7 3v4a1 1 0 0 0 1 1h7"></path></svg>
            Eliminar planta
        `;

    const mapname = document.getElementById('mapname');
    const starttrackbtn = document.getElementById('starttrack');
    const stoptrackbtn = document.getElementById('stoptrack');
    const drawAreaButton = document.createElement('button');
    const drawWallButton = document.createElement('button');
    const addDeviceButton = document.createElement('button');
    const clearCanvasButton = document.createElement('button');
    const saveReceiverButton = document.createElement('button');
    const SetScaleButton = document.createElement('button');
    let img = new Image();
    let tmpcords = null;
    let finalcords = {
        floor: [] // Array to manage multiple floors
      };
    let tmpfinalcords = [];
    // Array to store circles
    const circles = [];
    let receiverName = "";
    let zoneName = "";
    let isDrawing = false;
    let SelMapName = "";
    let new_floor = true;
    let removefile = false;
    let imgfilename = "";
    let device = "";
    let myScaleVal = null;
    const calibrationSamples = {};
    let distanceEntityMap = {};
    let targetMetadata = {};
    let discoveredReceivers = [];
    let wallStartPoint = null;
    const wallPenaltyPresets = [0.8, 1.6, 2.5, 3.4, 4.5, 6.0];
    let proCalibrationPoint = null;
    let proPickPositionPending = false;

    const newelement = `
                <ul class="space-y-2" id="idxxx">
                        <li class="flex items-center justify-between bg-gray-50 p-2 rounded">
                            <span class="text-sm truncate">typename</span>
                            <div class="flex gap-2">
                                <button data-type="removexxx" data-id="idxxx" class="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&amp;_svg]:pointer-events-none [&amp;_svg]:size-4 [&amp;_svg]:shrink-0 hover:bg-accent hover:text-accent-foreground w-10">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-trash w-4 h-4"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                                </button>
                            </div>
                        </li>
                    </ul>
                `;

    // =================================================================
    // Fetch existing maps
    // =================================================================

        async function getSavedMaps(){
            const mapsResponse = await fetch('/api/bps/maps');
            if (!mapsResponse.ok) {
                console.error('Failed to fetch maps:', mapsResponse.statusText);
                alert('No se pudieron cargar los mapas.');
                return false;
            }
        
            const maps = await mapsResponse.json();
            mapSelector.innerHTML = '<option value="">--Selecciona una opción--</option>';
            maps.forEach(map => {
                const option = document.createElement('option');
                option.value = map;
                option.textContent = map;
                mapSelector.appendChild(option);
            });
            return true;
        }
        
    
        // Once the maps are loaded, call fetchBPSData
        let tmpsaved = await getSavedMaps();
        if (tmpsaved){
            fetchBPSData();
        }

        let socket = null;
        const tracked = [];
        let NewEnts = [];
        let socketIdCounter = 1; 

        function getDistanceEntityForSelection(targetId, receiverId) {
            if (!targetId || !receiverId) {
                return null;
            }
            const targetMap = distanceEntityMap[targetId] || {};
            const mapped = targetMap[receiverId];
            if (mapped) {
                return mapped;
            }
            // Legacy fallback for integrations that still expose the classic naming.
            return `sensor.${targetId}_distance_to_${receiverId}`;
        }

        function refreshReceiverSuggestions() {
            let datalist = document.getElementById("receiverSuggestions");
            if (!datalist) {
                datalist = document.createElement("datalist");
                datalist.id = "receiverSuggestions";
                document.body.appendChild(datalist);
            }
            datalist.innerHTML = "";
            discoveredReceivers.forEach(receiverId => {
                const option = document.createElement("option");
                option.value = receiverId;
                datalist.appendChild(option);
            });
        }

        function startTracking() {
            if (!checkCanvasImage()) return;
            if (!mapname.value) {
                alert("Selecciona o crea una planta.");
                return;
            }
            if (socket){
                alert("Ya hay una conexión activa.");
                return;
            }

            if (!hass_token || !hassURL){
                let messageStr = "";
                if (!hass_token){
                    messageStr = "Debes añadir un token de larga duración";
                }
                if (!hass_token && !hassURL){
                    messageStr = messageStr+" y la URL de HA. Revisa la documentación.";
                    alert(messageStr);
                    return;
                }
                if (!hassURL){
                    messageStr = "Debes añadir la URL de HA";
                }
                alert(messageStr);
                return;
            }
            
            //Build the array with tracked devices
            if (device == ""){
                alert("Debes elegir un dispositivo para seguir.");
                return;
            }
            tracked.length = 0;
            let floor = getCurrentFloor();
            if (!floor) {
                alert("Selecciona una planta válida antes de iniciar el seguimiento.");
                return;
            }
            floor.receivers.forEach((entity, index) => {
                const distanceEntityId = getDistanceEntityForSelection(device, entity.entity_id);
                if (distanceEntityId) {
                    tracked.push(distanceEntityId);
                }
            });

            // Check if there are enough points for trilateration
            if (tracked.length < 3) {
                alert("Se requieren al menos tres receptores para el seguimiento.");
                return;
            }
    
            console.log("open socket");
            socket = new WebSocket("wss://"+hassURL+"/api/websocket");
            socket.onopen = () => {
                // Send authentication
                console.log("sending auth");
                socket.send(JSON.stringify({ type: "auth", access_token: hass_token }));
    
                // Once authentication is complete, subscribe
                socket.onmessage = async (event) => {
                    let message = JSON.parse(event.data);
                    if (message.type === "auth_ok") {
                        console.log("auth ok");
                        starttrackbtn.style.display = "none";
                        stoptrackbtn.style.display = "";
                        // Subscribe to entiteter
                        socket.send(JSON.stringify({
                            id: 1, // Unique ID for this message
                            type: "bps/subscribe",
                            entities: tracked,
                        }));
                    }
            
                    if (message.type === "state_changed") {
                        await updateEntArray(message.entity_id, message.new_state);
                        socketIdCounter++;
                        const triData = NewEnts.map(item => item.cords);
                        socket.send(JSON.stringify({
                            id: socketIdCounter,
                            type: "bps/known_points",
                            knownPoints: triData,
                        }));
                    }

                    // Handle the response from knownPoints
                    if (message.type === "tri_result" && message.success) {
                        drawTracker(message.result);
                    } else if (message.type === "tri_result" && !message.success) {
                        console.log("Tri Error: "+message);
                    }
    
                    let current = false;
                    if (message.current_states && Array.isArray(message.current_states)) {
                        current = true;
                    } else {
                        current = false;
                    }

                    if (message.type === "result" && current) {
                        let floor = finalcords.floor.find(floor => floor.name === SelMapName);
                        message.current_states.forEach((entity, index) => {
                            updateEntArray(entity.entity_id, entity.state);
                        });
                        console.log("Registered array");
                        console.log(NewEnts);
                    } else if (message.type === "result" && !message.success) {
                        console.log("Result Error: "+message);
                    }
                };
            };

        }

        function stopTracking(){
            if (!checkCanvasImage()) return;
            if (!mapname.value) {
                alert("Introduce un nombre de planta.");
                return;
            }
            if (!socket){
                alert("No hay conexión activa.");
                return;
            }
            socket.send(JSON.stringify({
                id: 2, // Unique ID for this message
                type: "bps/unsubscribe",
                entities: tracked,
            }));
            socket.close();
            socket = null;
            console.log(`Unsubscribed`);
            starttrackbtn.style.display = "";
            stoptrackbtn.style.display = "none";
        }

        let stoptrackstat = false;
        function startTrackfunc(){
            stoptrackstat = false;
            starttrackbtn.style.display = "none";
            stoptrackbtn.style.display = "";
            const interval = setInterval(async () => {
                if (stoptrackstat) {
                    clearInterval(interval);
                    stoptrackstat = false;
                    starttrackbtn.style.display = "";
                    stoptrackbtn.style.display = "none";
                    zonediv.style.display = "none";
                    return;
                }
                let apiresponse = await fetchBPSCords();
                if (!Array.isArray(apiresponse)) {
                    return;
                }
                let result = apiresponse.find(item => item.ent === device);
                if (!result || !Array.isArray(result.cords) || result.cords.length < 2) {
                    return;
                }
                let dt = {x: result.cords[0], y:result.cords[1]};
                drawTracker(dt);
                zonediv.style.display = "";
                document.getElementById("zonevalue").textContent = result.zone;
            }, 500); // Run every half second
        }

        function stoptrackfunc(){
            stoptrackstat = true;
        }

        starttrackbtn.addEventListener("click", function() {
            stoptrackbtn.removeEventListener("click", stopTracking);
            stoptrackbtn.removeEventListener("click", stoptrackfunc);
            if (document.getElementById("myCheckbox").checked) {
                startTracking();
                stoptrackbtn.addEventListener("click", stopTracking);
            } else {
                startTrackfunc();
                stoptrackbtn.addEventListener("click", stoptrackfunc);
            }
        });

        async function updateEntArray(eid, state){
            let newEid = eid.split("_distance_to_")[1];
            let index = NewEnts.findIndex(item => item.eid === newEid);
            if (state !== 'unknown') {
                
                let floor = getCurrentFloor();
                if (!floor) {
                    return;
                }
                let rec = floor.receivers.find(element => element.entity_id === newEid);
                if (!rec) {
                    return;
                }
                const rawDistance = parseFloat(state);
                if (Number.isNaN(rawDistance)) {
                    return;
                }
                const correctedMeters = getCalibratedDistance(rawDistance, rec);
                if (index !== -1) {
                    //The entity exists, update
                    NewEnts.splice(index, 1, {
                        eid: newEid,
                        cords: [
                            NewEnts[index].cords[0], // Keep existing x
                            NewEnts[index].cords[1], // Keep existing y
                            correctedMeters * floor.scale      // Update z
                        ]
                    });
                    
                } else {
                    NewEnts.push({
                        eid: newEid, 
                        cords: [rec.cords.x, rec.cords.y, correctedMeters * floor.scale]
                    });
                }
            } 
            if (state == 'unknown') {
                if (index !== -1) {
                    //Remove the entity from the array
                    NewEnts = NewEnts.filter(item => item.eid !== newEid);
                } 
            }
            await new Promise((resolve) => setTimeout(resolve, 100));
        }

    // =================================================================
    // Triliterate functionality
    // =================================================================
    const dataURL = null;
    let urlBol = false;

    function drawTracker(tricords){
        if(!urlBol){
            const dataURL = canvas.toDataURL('image/png');
            img.src = dataURL;
            urlBol = true;
        }
        clearCanvas();
        
        const iconSize = canvas.width * 0.04; // Adjust size as needed
        const x = tricords.x;
        const y = tricords.y;
        const icon = new Image();
        icon.src = "person.svg";
        icon.onload = () => {
            ctx.drawImage(icon, x - iconSize / 2, y - iconSize / 2, iconSize, iconSize);
        };
    }

    // =================================================================
    // Other functions
    // =================================================================
        // Function to fetch data from the API and display it on page
        async function fetchBPSData() {
            const apiUrl = "/api/bps/read_text"; // API endpoint to read the file
        
            try {
                const response = await fetch(apiUrl); // Make a GET request to the API
        
            if (!response.ok) {
                console.error("Failed to fetch BPS data:", response.statusText); // Handle error status
                return;
            }
        
            const data = await response.json();
        
            finalcords = data.coordinates ? JSON.parse(data.coordinates) : { floor: [] };
            if (!Array.isArray(finalcords.floor)) {
                finalcords.floor = [];
            }
            normalizeAllFloors();
            tmpfinalcords = finalcords; //Store original cords in a temp to compare later if it is changed
            console.log("Coordinates loaded:", finalcords);
            distanceEntityMap = data.distance_entity_map || {};
            targetMetadata = data.target_metadata || {};
            discoveredReceivers = Array.from(
                new Set(
                    Object.values(distanceEntityMap).flatMap(receiverMap => Object.keys(receiverMap || {}))
                )
            ).sort();
            refreshReceiverSuggestions();
            const entityOptions = Array.isArray(data.entity_options) && data.entity_options.length > 0
                ? data.entity_options
                : (data.entities || []).map(ent => ({ id: ent, name: ent }));
            console.log("Entities to track:", entityOptions);

            entSelector.innerHTML = '<option value="">--Selecciona una opción--</option>';
            entityOptions.forEach(ent => {
                const option = document.createElement('option');
                option.value = ent.id;
                option.textContent = ent.name || ent.id;
                entSelector.appendChild(option);
            });
            refreshCalibrationSelectors();

            } catch (error) {
                console.error("Error fetching BPS data:", error); // Handle possible error during fetch-call
            }
        }

        async function fetchBPSCords() {
            const apiUrl = "/api/bps/cords"; 
        
            try {
                const response = await fetch(apiUrl); // Make a GET request to the API
        
            if (!response.ok) {
                console.error("Failed to fetch BPS data:", response.statusText); // Handle error status
                return;
            }
        
            const data = await response.json();
            return data;

            } catch (error) {
            // Handle possible error during fetch-call
            console.error("Error fetching BPS data:", error);
            }
        }

        // Choose which entity to track
        entSelector.addEventListener('change', async () => {
            if(entSelector.value){
                console.log("väljare");
                if (socket) {
                    stopTracking();
                } else {
                    stoptrackstat = true;
                }
                device = entSelector.value;
                starttrackbtn.style.display = "";
            } else {
                starttrackbtn.style.display = "none";
            }
        });

        if (calReceiverSelect) calReceiverSelect.addEventListener("change", loadCalibrationInputsForSelectedReceiver);
        if (calSaveManualButton) calSaveManualButton.addEventListener("click", saveManualCalibration);
        if (calCaptureSampleButton) {
            calCaptureSampleButton.addEventListener("click", async () => {
                await captureCalibrationSample();
            });
        }
        if (calComputeAutoButton) calComputeAutoButton.addEventListener("click", computeAutoCalibration);
        if (wallPenaltySaveButton) wallPenaltySaveButton.addEventListener("click", saveWallPenalty);
        if (wallPenaltyPresetSelect) wallPenaltyPresetSelect.addEventListener("change", applyWallPenaltyPreset);
        if (calProPickPositionButton) calProPickPositionButton.addEventListener("click", startProPositionPick);
        if (calProAutoButton) calProAutoButton.addEventListener("click", runProAutoCalibration);
    
    
    // Check if the image is loaded in the canvas
    function checkCanvasImage() {
        if (canvas.width === 0 || canvas.height === 0) {
            alert("Carga primero un plano.");
            return false;
        }
        return true;
    }

    function getCurrentFloor() {
        const floorName = (SelMapName || mapname.value || "").trim();
        if (!floorName) {
            return null;
        }
        SelMapName = floorName;
        const floor = finalcords.floor.find(floor => floor.name === floorName) || null;
        if (floor) {
            ensureFloorDefaults(floor);
        }
        return floor;
    }

    function ensureFloorDefaults(floor) {
        if (!floor || typeof floor !== "object") {
            return;
        }
        if (!Array.isArray(floor.receivers)) {
            floor.receivers = [];
        }
        if (!Array.isArray(floor.zones)) {
            floor.zones = [];
        }
        if (!Array.isArray(floor.walls)) {
            floor.walls = [];
        }
        const parsedPenalty = parseFloat(floor.wall_penalty);
        floor.wall_penalty = Number.isFinite(parsedPenalty) && parsedPenalty >= 0 ? parsedPenalty : 2.5;
    }

    function normalizeAllFloors() {
        if (!Array.isArray(finalcords.floor)) {
            finalcords.floor = [];
            return;
        }
        finalcords.floor.forEach(ensureFloorDefaults);
    }

    function ensureReceiverCalibration(receiver) {
        if (!receiver.calibration || typeof receiver.calibration !== "object") {
            receiver.calibration = { factor: 1, offset: 0 };
        }
        if (Number.isNaN(parseFloat(receiver.calibration.factor))) {
            receiver.calibration.factor = 1;
        }
        if (Number.isNaN(parseFloat(receiver.calibration.offset))) {
            receiver.calibration.offset = 0;
        }
        return receiver.calibration;
    }

    function getCalibratedDistance(rawDistance, receiver) {
        const calibration = ensureReceiverCalibration(receiver);
        const factor = parseFloat(calibration.factor ?? 1);
        const offset = parseFloat(calibration.offset ?? 0);
        const corrected = (rawDistance * factor) + offset;
        return Math.max(corrected, 0);
    }

    function refreshCalibrationStatus() {
        if (!calStatus || !calReceiverSelect) {
            return;
        }
        const receiverId = calReceiverSelect.value;
        const samples = calibrationSamples[receiverId] || [];
        const sampleText = samples.length > 0 ? `Muestras: ${samples.length}` : "Sin muestras de calibración.";
        calStatus.textContent = sampleText;
    }

    function loadWallPenaltyForCurrentFloor() {
        if (!wallPenaltyInput || !wallPenaltyPresetSelect) {
            return;
        }
        const floor = getCurrentFloor();
        if (!floor) {
            wallPenaltyInput.value = "";
            wallPenaltyPresetSelect.value = "";
            return;
        }
        const currentPenalty = Number(floor.wall_penalty ?? 2.5);
        wallPenaltyInput.value = currentPenalty.toFixed(2);
        wallPenaltyPresetSelect.value = matchPenaltyPreset(currentPenalty);
    }

    function matchPenaltyPreset(value) {
        const parsed = Number(value);
        if (!Number.isFinite(parsed)) {
            return "";
        }
        for (const preset of wallPenaltyPresets) {
            if (Math.abs(preset - parsed) < 0.05) {
                return preset.toString();
            }
        }
        return "";
    }

    function applyWallPenaltyPreset() {
        if (!wallPenaltyPresetSelect || !wallPenaltyInput) {
            return;
        }
        const selected = parseFloat(wallPenaltyPresetSelect.value);
        if (!Number.isFinite(selected)) {
            return;
        }
        wallPenaltyInput.value = selected.toFixed(2);
    }

    function saveWallPenalty() {
        if (!wallPenaltyInput) {
            return;
        }
        const floor = getCurrentFloor();
        if (!floor) {
            alert("Selecciona primero una planta.");
            return;
        }
        const penalty = parseFloat(wallPenaltyInput.value);
        if (!Number.isFinite(penalty) || penalty < 0) {
            alert("La penalización por pared debe ser un número mayor o igual a 0.");
            return;
        }
        floor.wall_penalty = penalty;
        if (wallPenaltyPresetSelect) {
            wallPenaltyPresetSelect.value = matchPenaltyPreset(penalty);
        }
        savebuttondiv.appendChild(saveButton);
        if (calStatus) {
            calStatus.textContent = `Penalización por pared guardada: ${penalty.toFixed(2)} m`;
        }
    }

    function updateProStatus(message) {
        if (!calProStatus) {
            return;
        }
        calProStatus.textContent = message;
    }

    function startProPositionPick() {
        const floor = getCurrentFloor();
        if (!floor) {
            alert("Selecciona primero una planta/mapa.");
            return;
        }
        if (!checkCanvasImage()) return;
        removeListeners();
        buttonreset();
        proPickPositionPending = true;
        canvas.style.cursor = "crosshair";
        updateProStatus("Pro: haz clic en el mapa para marcar tu posición real.");
        canvas.addEventListener("click", handleProPositionClick);
    }

    function handleProPositionClick(event) {
        if (!proPickPositionPending) {
            return;
        }
        const floor = getCurrentFloor();
        if (!floor) {
            return;
        }
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        proCalibrationPoint = {
            floor: floor.name,
            x: (event.clientX - rect.left) * scaleX,
            y: (event.clientY - rect.top) * scaleY,
        };
        proPickPositionPending = false;
        canvas.style.cursor = "";
        canvas.removeEventListener("click", handleProPositionClick);
        updateProStatus(
            `Pro: posición marcada en (${proCalibrationPoint.x.toFixed(0)}, ${proCalibrationPoint.y.toFixed(0)}).`
        );
        clearCanvas();
        drawElements();
    }

    function computeAutoCalibrationForSamples(samples) {
        let factor = 1;
        let offset = 0;
        if (!samples || samples.length === 0) {
            return null;
        }
        if (samples.length === 1) {
            const only = samples[0];
            factor = only.measured / only.observed;
        } else {
            const n = samples.length;
            const sumX = samples.reduce((acc, s) => acc + s.observed, 0);
            const sumY = samples.reduce((acc, s) => acc + s.measured, 0);
            const sumXY = samples.reduce((acc, s) => acc + (s.observed * s.measured), 0);
            const sumXX = samples.reduce((acc, s) => acc + (s.observed * s.observed), 0);
            const denominator = (n * sumXX) - (sumX * sumX);
            if (Math.abs(denominator) < 1e-9) {
                factor = samples.reduce((acc, s) => acc + (s.measured / s.observed), 0) / n;
                offset = 0;
            } else {
                factor = ((n * sumXY) - (sumX * sumY)) / denominator;
                offset = (sumY - (factor * sumX)) / n;
            }
        }
        if (!Number.isFinite(factor) || factor <= 0) {
            return null;
        }
        if (!Number.isFinite(offset)) {
            offset = 0;
        }
        return { factor, offset };
    }

    function getRealDistanceMeters(point, receiver, floor) {
        const dx = Number(receiver.cords?.x) - Number(point.x);
        const dy = Number(receiver.cords?.y) - Number(point.y);
        const pixelDistance = Math.sqrt((dx * dx) + (dy * dy));
        return pixelDistance / Number(floor.scale);
    }

    function delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    async function runProAutoCalibration() {
        const floor = getCurrentFloor();
        const deviceId = calEntitySelect?.value || "";
        if (!floor || !Number.isFinite(Number(floor.scale)) || Number(floor.scale) <= 0) {
            alert("Necesitas una planta con escala configurada.");
            return;
        }
        if (!deviceId) {
            alert("Selecciona un dispositivo en Calibración para usar Modo Pro.");
            return;
        }
        if (!proCalibrationPoint || proCalibrationPoint.floor !== floor.name) {
            alert("Primero marca tu posición real en este mapa.");
            return;
        }
        updateProStatus("Pro: capturando durante 15 segundos... espera sin moverte.");

        const sessionCaptured = new Set();
        const receivers = floor.receivers || [];

        for (let t = 0; t < 15; t++) {
            await Promise.all(
                receivers.map(async (receiver) => {
                    const receiverId = receiver.entity_id;
                    try {
                        const observed = await readStateValue("", deviceId, receiverId);
                        if (!Number.isFinite(observed) || observed <= 0) {
                            return;
                        }
                        const measured = getRealDistanceMeters(proCalibrationPoint, receiver, floor);
                        if (!Number.isFinite(measured) || measured <= 0) {
                            return;
                        }
                        calibrationSamples[receiverId] = calibrationSamples[receiverId] || [];
                        calibrationSamples[receiverId].push({ observed, measured });
                        sessionCaptured.add(receiverId);
                    } catch (err) {
                        // Receiver/device pair has no readable value in this snapshot.
                    }
                })
            );
            updateProStatus(`Pro: capturando... ${t + 1}/15 s`);
            await delay(1000);
        }

        let calibratedCount = 0;
        receivers.forEach((receiver) => {
            const samples = calibrationSamples[receiver.entity_id] || [];
            const result = computeAutoCalibrationForSamples(samples);
            if (!result) {
                return;
            }
            receiver.calibration = {
                factor: result.factor,
                offset: result.offset,
            };
            calibratedCount += 1;
        });

        const missingNow = receivers
            .map(r => r.entity_id)
            .filter(id => !sessionCaptured.has(id));
        savebuttondiv.appendChild(saveButton);
        drawElements();
        if (missingNow.length > 0) {
            updateProStatus(
                `Pro: calibrados ${calibratedCount}/${receivers.length}. Mueve el móvil hacia: ${missingNow.join(", ")} y repite.`
            );
        } else {
            updateProStatus(`Pro: calibración completada para ${calibratedCount}/${receivers.length} receptores.`);
        }
    }

    function loadCalibrationInputsForSelectedReceiver() {
        if (!calReceiverSelect || !calFactorInput || !calOffsetInput) {
            return;
        }
        const floor = getCurrentFloor();
        if (!floor || !calReceiverSelect.value) {
            calFactorInput.value = "";
            calOffsetInput.value = "";
            refreshCalibrationStatus();
            return;
        }

        const receiver = floor.receivers.find(r => r.entity_id === calReceiverSelect.value);
        if (!receiver) {
            calFactorInput.value = "";
            calOffsetInput.value = "";
            refreshCalibrationStatus();
            return;
        }

        const calibration = ensureReceiverCalibration(receiver);
        calFactorInput.value = Number(calibration.factor).toFixed(3);
        calOffsetInput.value = Number(calibration.offset).toFixed(3);
        refreshCalibrationStatus();
    }

    function refreshCalibrationSelectors() {
        if (!calReceiverSelect || !calEntitySelect) {
            return;
        }
        const floor = getCurrentFloor();
        const previousReceiver = calReceiverSelect.value;
        const previousEntity = calEntitySelect.value;

        calReceiverSelect.innerHTML = '<option value="">Receptor...</option>';
        if (floor) {
            floor.receivers.forEach(receiver => {
                const option = document.createElement("option");
                option.value = receiver.entity_id;
                option.textContent = receiver.entity_id;
                calReceiverSelect.appendChild(option);
            });
        }
        if (previousReceiver) {
            calReceiverSelect.value = previousReceiver;
        } else if (floor && floor.receivers.length > 0) {
            calReceiverSelect.value = floor.receivers[0].entity_id;
        }

        calEntitySelect.innerHTML = '<option value="">Dispositivo...</option>';
        Array.from(entSelector.options).forEach(opt => {
            if (!opt.value) return;
            const option = document.createElement("option");
            option.value = opt.value;
            option.textContent = opt.value;
            calEntitySelect.appendChild(option);
        });
        if (previousEntity) {
            calEntitySelect.value = previousEntity;
        } else if (calEntitySelect.options.length > 1) {
            calEntitySelect.selectedIndex = 1;
        }

        loadCalibrationInputsForSelectedReceiver();
        loadWallPenaltyForCurrentFloor();
    }

    async function readStateValue(entityId = "", targetId = "", receiverId = "") {
        let query = "";
        if (entityId) {
            query = `entity_id=${encodeURIComponent(entityId)}`;
        } else if (targetId && receiverId) {
            query = `target_id=${encodeURIComponent(targetId)}&receiver_id=${encodeURIComponent(receiverId)}`;
        } else {
            throw new Error("Missing entity or target/receiver for readStateValue");
        }

        const response = await fetch(`/api/bps/distance?${query}`);
        if (!response.ok) {
            throw new Error(`Cannot read ${entityId}: ${response.status}`);
        }
        const stateObj = await response.json();
        const value = parseFloat(stateObj.value);
        if (Number.isNaN(value)) {
            throw new Error(`State ${entityId} is not numeric`);
        }
        return value;
    }

    function saveManualCalibration() {
        const floor = getCurrentFloor();
        const receiverId = calReceiverSelect.value;
        if (!floor || !receiverId) {
            alert("Selecciona primero una planta/mapa y un receptor.");
            return;
        }

        const factor = parseFloat(calFactorInput.value);
        const offset = parseFloat(calOffsetInput.value || "0");
        if (Number.isNaN(factor) || factor <= 0) {
            alert("El factor debe ser un número mayor que 0.");
            return;
        }
        if (Number.isNaN(offset)) {
            alert("El offset debe ser numérico.");
            return;
        }

        const receiver = floor.receivers.find(r => r.entity_id === receiverId);
        if (!receiver) {
            alert("No se encontró el receptor en la planta seleccionada.");
            return;
        }

        receiver.calibration = { factor, offset };
        savebuttondiv.appendChild(saveButton);
        drawElements();
        if (calStatus) {
            calStatus.textContent = `Calibración manual guardada para ${receiverId}.`;
        }
    }

    async function captureCalibrationSample() {
        const floor = getCurrentFloor();
        const receiverId = calReceiverSelect.value;
        const deviceId = calEntitySelect.value;
        const measuredMeters = parseFloat(calMeasuredMetersInput.value);

        if (!floor || !receiverId || !deviceId) {
            alert("Selecciona primero planta/mapa, receptor y dispositivo.");
            return;
        }
        if (Number.isNaN(measuredMeters) || measuredMeters <= 0) {
            alert("Los metros medidos deben ser mayores que 0.");
            return;
        }

        const distanceEntity = getDistanceEntityForSelection(deviceId, receiverId);
        if (!distanceEntity) {
            alert(`No se encontró entidad de distancia para ${deviceId} -> ${receiverId}.`);
            return;
        }
        try {
            const observed = await readStateValue(distanceEntity, deviceId, receiverId);
            if (!calibrationSamples[receiverId]) {
                calibrationSamples[receiverId] = [];
            }
            calibrationSamples[receiverId].push({
                observed,
                measured: measuredMeters,
            });
            refreshCalibrationStatus();
            if (calStatus) {
                calStatus.textContent = `Muestra ${calibrationSamples[receiverId].length}: observado ${observed.toFixed(2)} m, real ${measuredMeters.toFixed(2)} m.`;
            }
            calMeasuredMetersInput.value = "";
        } catch (err) {
            console.error("Calibration capture error:", err);
            alert(`No se pudo capturar muestra de ${distanceEntity}.`);
        }
    }

    function computeAutoCalibration() {
        const floor = getCurrentFloor();
        const receiverId = calReceiverSelect.value;
        if (!floor || !receiverId) {
            alert("Selecciona primero un receptor.");
            return;
        }
        const samples = calibrationSamples[receiverId] || [];
        if (samples.length === 0) {
            alert("Captura al menos una muestra primero.");
            return;
        }
        const result = computeAutoCalibrationForSamples(samples);
        if (!result) {
            alert("El factor calculado no es válido. Captura muestras más limpias.");
            return;
        }

        const receiver = floor.receivers.find(r => r.entity_id === receiverId);
        if (!receiver) {
            alert("No se encontró el receptor.");
            return;
        }

        receiver.calibration = { factor: result.factor, offset: result.offset };
        calFactorInput.value = result.factor.toFixed(3);
        calOffsetInput.value = result.offset.toFixed(3);
        savebuttondiv.appendChild(saveButton);
        drawElements();
        if (calStatus) {
            calStatus.textContent = `Autocalibración aplicada a ${receiverId}: factor ${result.factor.toFixed(3)}, offset ${result.offset.toFixed(3)}.`;
        }
    }

    // Remove all listeners
    function removeListeners(){
        canvas.removeEventListener("mousedown", selectHandle);
        canvas.removeEventListener("mousemove", resizeRectangle);
        canvas.removeEventListener("mouseup", setHandles);
        canvas.removeEventListener("mousedown", startDrawingZone);
        canvas.removeEventListener("mouseup", endDrawingScale);
        canvas.removeEventListener('click', placeReceiver);
        canvas.removeEventListener("click", handleWallClick);
        canvas.removeEventListener("click", handleProPositionClick);
        canvas.style.cursor = "";
        proPickPositionPending = false;
    }

    //Reset all buttons
    function buttonreset(){
        if (scaleInputElement) {scaleInputElement.style.display = "none";}
        SetScaleButton.innerHTML = SetScaleButton.innerHTML.replace("Guardar escala","Establecer escala");
        SetScaleButton.setAttribute('data-active', 'false');
        if (entityInput) {entityInput.style.display = "none";}
        addDeviceButton.innerHTML = addDeviceButton.innerHTML.replace("Guardar receptor","Colocar receptor");
        addDeviceButton.setAttribute('data-active', 'false');
        if (zoneInputElement) {zoneInputElement.style.display = "none";}
        drawAreaButton.innerHTML = drawAreaButton.innerHTML.replace("Guardar zona","Dibujar zona");
        drawAreaButton.setAttribute('data-active', 'false');
        drawWallButton.innerHTML = drawWallButton.innerHTML.replace("Terminar paredes","Dibujar pared");
        drawWallButton.setAttribute('data-active', 'false');
        messdiv.innerHTML = "";
        wallStartPoint = null;
    }

    document.addEventListener('click', (event) => {
        // Check if the clicked element has the attribute data-type="removerec"
        if (event.target.closest('[data-type="removerec"]')) {
            const button = event.target.closest('[data-type="removerec"]'); // Get the button that was pressed
            const idToRemove = button.getAttribute('data-id'); // Get the value from data-id
            const elementToRemove = document.getElementById(idToRemove); // Find the element with the specific ID
            if (elementToRemove) { // Remove element if it exists
                console.log(`Receiver with ID "${idToRemove}" was removed.`);
                elementToRemove.remove();
            } else {
                console.log(`Receiver with ID "${idToRemove}" was not found.`);
                return;
            }
            // Loop through each floor and remove receivers where the entity_id matches
            finalcords.floor.forEach(floor => {
                if (floor.name === SelMapName) {
                    floor.receivers = floor.receivers.filter(receiver => receiver.entity_id !== idToRemove);
                }
            });
            delete calibrationSamples[idToRemove];
            console.log("Removed receiver");
            savebuttondiv.appendChild(saveButton);
            clearCanvas();
            drawElements();
        }
        if (event.target.closest('[data-type="removezone"]')) {
            const button = event.target.closest('[data-type="removezone"]'); // Get the button that was pressed
            const idToRemove = button.getAttribute('data-id'); // Get the value from data-id
            const elementToRemove = document.getElementById(idToRemove); // Find the element with the specific ID
            if (elementToRemove) { // Remove element if it exists
                elementToRemove.remove();
                console.log(`Zone with ID "${idToRemove}" was removed.`);
            } else {
                console.log(`Zone with ID "${idToRemove}" was not found.`);
                return;
            }
            // Loop through each floor and remove zones where the entity_id matches
            finalcords.floor.forEach(floor => {
                if (floor.name === SelMapName) {
                    floor.zones = floor.zones.filter(zone => zone.entity_id !== idToRemove);
                }
            });
            console.log("Removed zone");
            savebuttondiv.appendChild(saveButton);
            clearCanvas();
            drawElements();
        }
        if (event.target.closest('[data-type="removewall"]')) {
            const button = event.target.closest('[data-type="removewall"]');
            const index = parseInt(button.getAttribute('data-index'), 10);
            const floor = getCurrentFloor();
            if (floor && Number.isInteger(index) && index >= 0 && index < floor.walls.length) {
                floor.walls.splice(index, 1);
                savebuttondiv.appendChild(saveButton);
                clearCanvas();
                drawElements();
            }
        }
        if (event.target.closest('[data-type="collapse"]')) {
            const collapseDiv = event.target.closest('[data-type="collapse"]');
            const parent = collapseDiv.closest('.fixed'); // Find the nearest parent element to collapseDiv
        
            // Toggle between minimized and normal size
            if (parent.classList.contains('collapsed')) {
                // Reset size
                parent.classList.remove('collapsed');
                parent.style.maxHeight = '80vh'; // Reset height
                parent.querySelectorAll('.space-y-4, #message').forEach(el => {
                    el.style.display = ''; // Show element
                });
            } else {
                // Minimize
                parent.classList.add('collapsed');
                const computedStyleCD = window.getComputedStyle(collapseDiv);
                const computedStyleP = window.getComputedStyle(parent);
                const newheight = parseFloat(computedStyleCD.height) + parseFloat(computedStyleP.paddingTop) + parseFloat(computedStyleP.paddingBottom) - parseFloat(computedStyleCD.paddingBottom);
                parent.style.maxHeight = `${newheight}px`; // Adjust height to collapseDiv
                parent.querySelectorAll('.space-y-4, #message').forEach(el => {
                    el.style.display = 'none'; // Hide element
                });
            }
        }
    });

    // =================================================================
    // Clear canvas functionality
    // =================================================================

    clearCanvasButton.addEventListener('click', () => {
        if (!checkCanvasImage()) return;
        removeListeners();
        drawAreaButton.remove();
        drawWallButton.remove();
        addDeviceButton.remove();
        clearCanvasButton.remove();
        SetScaleButton.remove();
        saveButton.remove();
        deleteButton.remove();
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        mapname.value = "";
        SelMapName = "";
        buttonreset();
        mapSelector.selectedIndex = 0;
        refreshCalibrationSelectors();
        updateProStatus("Pro: pendiente de marcar posición.");
    });

    function clearCanvas(){
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        setupImageSize(img, canvas);
        messdiv.innerHTML = "";
    }

    // =================================================================
    // Draw zones
    // =================================================================

    let rectangle = null;
    let handles = [];
    let tmphandles = [];
    let selectedHandle = null;
    let zonecords = [];
    let zoneInputElement = null; // För att hantera input-fältet

    drawAreaButton.addEventListener("click", () => {
        if (!checkCanvasImage()) return;
        removeListeners();
        clearCanvas();
        drawElements();

        if (drawAreaButton.dataset.active === 'false') {
            buttonreset();
            canvas.addEventListener("mousedown", startDrawingZone);
            drawAreaButton.innerHTML = drawAreaButton.innerHTML.replace("Dibujar zona","Guardar zona");
            drawAreaButton.setAttribute('data-active', 'true');
            messdiv.innerHTML = '<h4 class="font-medium mb-2">Instrucciones</h4><p class="text-sm text-gray-500">Crea una zona haciendo clic en el plano. Ajusta el tamaño arrastrando las esquinas y escribe el nombre de la zona.</p>';
        } else if (drawAreaButton.dataset.active === 'true') {
            if (!mapname.value) {
                alert("Introduce un nombre de planta.");
                return;
            }
            SelMapName = mapname.value;
            if (!rectangle) {
                alert("No se ha dibujado ninguna zona.");
                return;
            }
            zoneName = document.getElementById('zoneName').value.trim();
            if (!zoneName) {
                alert("Indica un nombre para la zona.");
                return;
            }

            zonecords = [
                { x: rectangle.x, y: rectangle.y },
                { x: rectangle.x + rectangle.width, y: rectangle.y },
                { x: rectangle.x, y: rectangle.y + rectangle.height },
                { x: rectangle.x + rectangle.width, y: rectangle.y + rectangle.height }
            ];
            let newZone = {
                entity_id: zoneName,
                cords: zonecords
              }; 
            if(addDataToFloor(finalcords, SelMapName, "zones", newZone)){
                alert(`Zona guardada: ${zoneName}`);
                console.log("Saved coordinates:", zonecords);
                buttonreset();
                zoneInputElement.value = "";
                clearCanvas();
                drawElements();
            }
            
        }
    });

    const handleSize = 15;
    function startDrawingZone(event) {
        const rect = canvas.getBoundingClientRect();
        
        const scaleX = canvas.width / rect.width; // Horisontal scale
        const scaleY = canvas.height / rect.height; // Vertical scale

        const centerX = (event.clientX - rect.left) * scaleX;
        const centerY = (event.clientY - rect.top) * scaleY;
    
        rectangle = {
            x: centerX - 100,
            y: centerY - 100,
            width: 200,
            height: 200
        };
    
        handles = [
            { x: rectangle.x - handleSize, y: rectangle.y - handleSize },
            { x: rectangle.x + rectangle.width - handleSize, y: rectangle.y - handleSize },
            { x: rectangle.x - handleSize, y: rectangle.y + rectangle.height - handleSize },
            { x: rectangle.x + rectangle.width - handleSize, y: rectangle.y + rectangle.height - handleSize }
        ];

        tmphandles = handles;
    
        drawRectangle();
        canvas.removeEventListener("mousedown", startDrawingZone);
        canvas.addEventListener("mousedown", selectHandle);
        canvas.addEventListener("mousemove", resizeRectangle);
        canvas.addEventListener("mouseup", setHandles);
    }

    // =================================================================
    // Draw walls
    // =================================================================

    drawWallButton.addEventListener("click", () => {
        if (!checkCanvasImage()) return;
        removeListeners();
        clearCanvas();
        drawElements();

        if (drawWallButton.dataset.active === 'false') {
            buttonreset();
            drawWallButton.setAttribute('data-active', 'true');
            drawWallButton.innerHTML = drawWallButton.innerHTML.replace("Dibujar pared", "Terminar paredes");
            wallStartPoint = null;
            messdiv.innerHTML = '<h4 class="font-medium mb-2">Instrucciones</h4><p class="text-sm text-gray-500">Haz clic en el inicio y fin de cada pared. Cada 2 clics se guarda una pared recta.</p>';
            canvas.addEventListener("click", handleWallClick);
        } else {
            buttonreset();
            clearCanvas();
            drawElements();
        }
    });

    function handleWallClick(event) {
        const floor = getCurrentFloor();
        if (!floor) {
            alert("Selecciona una planta.");
            return;
        }
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        const point = {
            x: (event.clientX - rect.left) * scaleX,
            y: (event.clientY - rect.top) * scaleY,
        };

        if (!wallStartPoint) {
            wallStartPoint = point;
            clearCanvas();
            drawElements();
            ctx.beginPath();
            ctx.arc(point.x, point.y, 7, 0, Math.PI * 2);
            ctx.fillStyle = "#111827";
            ctx.fill();
            return;
        }

        if (Math.abs(wallStartPoint.x - point.x) < 1 && Math.abs(wallStartPoint.y - point.y) < 1) {
            return;
        }

        const wall = {
            x1: wallStartPoint.x,
            y1: wallStartPoint.y,
            x2: point.x,
            y2: point.y,
        };
        floor.walls.push(wall);
        wallStartPoint = null;
        savebuttondiv.appendChild(saveButton);
        clearCanvas();
        drawElements();
    }

    function setHandles(event){
        selectedHandle = null;
        tmphandles = handles;
    }

    function drawRectangle() {
        clearCanvas();
        drawElements();
    
        // Create the input field and place it above the line
        if (!zoneInputElement) {
            zoneInputElement = document.createElement("input");
            zoneInputElement.type = "text";
            zoneInputElement.id = "zoneName";
            zoneInputElement.placeholder = "Nombre";
            zoneInputElement.classList.add("zone-input");
            document.body.appendChild(zoneInputElement);
        }

        const rect = canvas.getBoundingClientRect();
        
        const scaleX = canvas.width / rect.width; // Horisontal scale
        const scaleY = canvas.height / rect.height; // Vertical scale

        const inputPosition = {
            left: ((rectangle.x + (rectangle.width/2))/ scaleX) + canvas.offsetLeft - zoneInputElement.offsetWidth / 2 + 40,
            top: (rectangle.y / scaleY) + canvas.offsetTop - 30 // 30 pixles above the line 
        };

        zoneInputElement.style.left = `${inputPosition.left - 20}px`;
        zoneInputElement.style.top = `${inputPosition.top - 10}px`;
        zoneInputElement.style.display = "block";
        zoneInputElement.style.position = "absolute";

        // Draw rectangle
        ctx.beginPath();
        ctx.rect(rectangle.x, rectangle.y, rectangle.width, rectangle.height);
        ctx.strokeStyle = "red";
        ctx.lineWidth = 2;
        ctx.stroke();
    
        // Draw handles
        handles.forEach(handle => {
            ctx.beginPath();
            ctx.arc(handle.x + handleSize, handle.y + handleSize, handleSize, 0, Math.PI * 2);
            ctx.fillStyle = "red";
            ctx.fill();
        });
    }

    function selectHandle(event) {
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width; // Horisontal scale
        const scaleY = canvas.height / rect.height; // Vertical scale
        const mouseX = (event.clientX - rect.left) * scaleX;
        const mouseY = (event.clientY - rect.top) * scaleY;
    
        selectedHandle = handles.find(
            handle =>
                mouseX >= handle.x - (handleSize * 2) &&
                mouseX <= handle.x + (handleSize * 2) &&
                mouseY >= handle.y - (handleSize * 2) &&
                mouseY <= handle.y + (handleSize * 2)
        );
    }

    function resizeRectangle(event) {
        if (!selectedHandle) return;
    
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width; // Horisontal scale
        const scaleY = canvas.height / rect.height; // Vertical scale
        const mouseX = (event.clientX - rect.left) * scaleX;
        const mouseY = (event.clientY - rect.top) * scaleY;
    
        if (selectedHandle === tmphandles[0]) {
            rectangle.width += rectangle.x - mouseX;
            rectangle.height += rectangle.y - mouseY;
            rectangle.x = mouseX;
            rectangle.y = mouseY;
        } else if (selectedHandle === tmphandles[1]) {
            rectangle.width = mouseX - rectangle.x;
            rectangle.height += rectangle.y - mouseY;
            rectangle.y = mouseY;
        } else if (selectedHandle === tmphandles[2]) {
            rectangle.width += rectangle.x - mouseX;
            rectangle.x = mouseX;
            rectangle.height = mouseY - rectangle.y;
        } else if (selectedHandle === tmphandles[3]) {
            rectangle.width = mouseX - rectangle.x;
            rectangle.height = mouseY - rectangle.y;
        }
    
        handles = [
            { x: rectangle.x - handleSize, y: rectangle.y - handleSize },
            { x: rectangle.x + rectangle.width - handleSize, y: rectangle.y - handleSize },
            { x: rectangle.x - handleSize, y: rectangle.y + rectangle.height - handleSize },
            { x: rectangle.x + rectangle.width - handleSize, y: rectangle.y + rectangle.height - handleSize }
        ];

        drawRectangle();
    }

    // =================================================================
    // Set the scale for the floor
    // =================================================================

    let startPoint = null;
    let endPoint = null;
    let scaleInputElement = null; 

    SetScaleButton.addEventListener("click", () => {
        if (!checkCanvasImage()) return;
        removeListeners();
        clearCanvas();
        drawElements();

        if (SetScaleButton.dataset.active === 'false') {
            buttonreset();
            SetScaleButton.innerHTML = SetScaleButton.innerHTML.replace("Establecer escala","Guardar escala");
            messdiv.innerHTML = '<h4 class="font-medium mb-2">Instrucciones</h4><p class="text-sm text-gray-500">Marca dos puntos de referencia y escribe la distancia real en metros.</p>';
            startPoint = null;
            endPoint = null;

            canvas.addEventListener("mousedown", startDrawingScale);
            canvas.addEventListener("mouseup", endDrawingScale);
            SetScaleButton.setAttribute('data-active', 'true');
        } else if (SetScaleButton.dataset.active === 'true') {
            saveScale();
        }
    });

    let countclick = 0;
    function startDrawingScale(event) {
        const rect = canvas.getBoundingClientRect();
        if(countclick === 0){
            const scaleX = canvas.width / rect.width; // Horisontal scale
            const scaleY = canvas.height / rect.height; // Vertical scale
            startPoint = { x: (event.clientX - rect.left) * scaleX, y: (event.clientY - rect.top) * scaleY };
            isDrawing = false;
            countclick++; // Add one to variable

            //Draw starting point
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = 'red'; // Set fill color
            ctx.beginPath(); // Draw a circle
            ctx.arc(startPoint.x, startPoint.y, 10, 0, Math.PI * 2); // Rita en cirkel
            ctx.fill(); // Fill circle

            return;
        }
        if(countclick === 1){
            isDrawing = true;
            countclick = 0;
        }
    }

    function endDrawingScale(event) {
        if (!isDrawing) return;
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width; // Horisontal scale
        const scaleY = canvas.height / rect.height; // Vertical scale
        endPoint = { x: (event.clientX - rect.left) * scaleX, y: (event.clientY - rect.top) * scaleY };
        isDrawing = false;

        if (startPoint.x === endPoint.x && startPoint.y === endPoint.y) {
            console.log("No line drawn")
            return;
        }

        ctx.beginPath();
        ctx.moveTo(startPoint.x, startPoint.y);
        ctx.lineTo(endPoint.x, endPoint.y);
        ctx.strokeStyle = "red"; // Make line red
        ctx.lineWidth = 4;       // Set thickness of line
        ctx.stroke();

        // Create input field and place it above line
        if (!scaleInputElement) {
            scaleInputElement = document.createElement("input");
            scaleInputElement.type = "number";
            scaleInputElement.id = "scaleValue";
            scaleInputElement.placeholder = "m";
            scaleInputElement.classList.add("scale-input");
            document.body.appendChild(scaleInputElement);
        }

        const lineMidpoint = {
            x: (startPoint.x + endPoint.x) / 2,
            y: (startPoint.y + endPoint.y) / 2
        };
        
        const inputPosition = {
            left: (lineMidpoint.x / scaleX) + canvas.offsetLeft - scaleInputElement.offsetWidth / 2 + 40,
            top: (lineMidpoint.y / scaleY) + canvas.offsetTop - 30
        };

        scaleInputElement.style.left = `${inputPosition.left}px`;
        scaleInputElement.style.top = `${inputPosition.top - 10}px`;
        scaleInputElement.style.display = "block";
        scaleInputElement.style.position = "absolute";
        scaleInputElement.style.width = "60px";
    }

    function saveScale() {
        if (!startPoint || !endPoint || startPoint.x === endPoint.x || startPoint.y === endPoint.y) {
            alert("Primero debes dibujar una línea.");
            return;
        }

        const scaleInput = parseFloat(scaleInputElement?.value || "");
        if (isNaN(scaleInput) || scaleInput <= 0) {
            alert("Introduce la distancia real en metros.");
            return;
        }

        if (!mapname.value) {
            alert("Debes indicar un nombre de planta.");
            return;
        }
        SelMapName = mapname.value;

        const dx = endPoint.x - startPoint.x;
        const dy = endPoint.y - startPoint.y;
        const lineLength = Math.sqrt(dx * dx + dy * dy); // Calculate length of drawn line
        (`Line length: ${lineLength}`);
        
        // Save scale
        myScaleVal = lineLength / scaleInput;
        if(addDataToFloor(finalcords, SelMapName, "scale", myScaleVal)){
            buttonreset(); //Reset buttons
            clearCanvas(); //Clear canvas
            drawElements(); //Draw elements
        }
    }
    // =================================================================

    // =================================================================
    // Place receiver functionality
    // =================================================================

    let entityInput = null; // To handle input field

    addDeviceButton.addEventListener('click', () => {
        if (!checkCanvasImage()) return;
        removeListeners();
        receiverName = "";

        if (addDeviceButton.dataset.active === 'false') {
            buttonreset();
            messdiv.innerHTML = '<h4 class="font-medium mb-2">Instrucciones</h4><p class="text-sm text-gray-500">Coloca los receptores BLE sobre el plano y escribe su identificador. Si Bermuda usa "..._distance_to_bluetooth_proxy_cocina", el receptor sería "bluetooth_proxy_cocina".</p>';
            
            canvas.addEventListener('click', placeReceiver);
            addDeviceButton.setAttribute('data-active', 'true');
            addDeviceButton.innerHTML = addDeviceButton.innerHTML.replace("Colocar receptor","Guardar receptor");

        } else if (addDeviceButton.dataset.active === 'true') {
            if (!mapname.value) {
                alert("Debes indicar un nombre de planta.");
                return;
            }
            SelMapName = mapname.value;
            receiverName = document.getElementById('receiverName').value.trim();
            
            if (
                !receiverName
                || !tmpcords
                || !Number.isFinite(tmpcords.x)
                || !Number.isFinite(tmpcords.y)
            ) {
                alert("Debes indicar las coordenadas del receptor.");
                return;
            }

            let newReceiver = {
                entity_id: receiverName,
                cords: tmpcords,
                calibration: {
                    factor: 1,
                    offset: 0
                }
              };
            
            if(addDataToFloor(finalcords, SelMapName, "receivers", newReceiver)){
                buttonreset();
                entityInput.value = "";
                clearCanvas();
                drawElements();
                console.log("Receptor guardado correctamente.");
            } else {
                console.log("Could not save data to array");
            }
        }
    });

    // =================================================================
    // Placera en BLE mottagare
    // =================================================================

    function placeReceiver(event) {

        clearCanvas(); // Remove all drawn elements from canvas
        const x = event.clientX;
        const y = event.clientY;

        drawElements(x, y, "receiver");

        if (!entityInput) {
            entityInput = document.createElement("input");
            entityInput.type = "text";
            entityInput.id = "receiverName";
            entityInput.placeholder = "Nombre";
            entityInput.setAttribute("list", "receiverSuggestions");
            entityInput.classList.add("rec-input");
            document.body.appendChild(entityInput);
        }

        const element = document.body;
        const myrect = element.getBoundingClientRect();
        const mx = event.clientX - myrect.left; // X relative element
        const my = event.clientY - myrect.top;  // Y relative element

        const inputPosition = {
            left: mx + (canvas.width * 0.04 / 2),
            top: my - (32/2)
        };
        entityInput.style.left = `${inputPosition.left}px`;
        entityInput.style.top = `${inputPosition.top}px`;
        entityInput.style.display = "block";
        entityInput.style.position = "absolute";
    }

    // =================================================================
    // Add data to array
    // =================================================================

    function addDataToFloor(finalcords, floorName, dataType, data) {
        // Check if floor is arratm else initiate it
        if (!Array.isArray(finalcords.floor)) {
            finalcords.floor = [];
        }
        
        let floorExists = finalcords.floor.some(floor => floor.name === floorName); // Check if floor exists

        if (!floorExists) {
            // Add floor if it does not exists
            finalcords.floor.push({
            name: floorName,
            scale: null,
            receivers: [],
            zones: [],
            walls: [],
            wall_penalty: 2.5
            });
            console.log(`Added new floor: ${floorName}`);
        } else {
            console.log(`Floor '${floorName}' already exists.`);
        }    
        
        let floor = finalcords.floor.find(floor => floor.name === floorName); // Find correct floor

        if (floor) {
            ensureFloorDefaults(floor);
            // Control if receiver/zone with the name already exists on the floor
            let enitityExists = null;
            let tmpname = null;
            if(dataType === "receivers"){
                if (!data.calibration) {
                    data.calibration = { factor: 1, offset: 0 };
                }
                enitityExists = floor[dataType].some(receiver => receiver.entity_id === data.entity_id);
                tmpname = data.entity_id;
            }
            if(dataType === "zones"){
                enitityExists = floor[dataType].some(zone => zone.entity_id === data.entity_id);
                tmpname = data.entity_id;
            }
            if(dataType === "walls"){
                floor.walls.push(data);
                savebuttondiv.appendChild(saveButton);
                return true;
            }
            if(dataType === "scale"){
                floor.scale = data;
                savebuttondiv.appendChild(saveButton);
                return true;
            }

            if (!enitityExists) {
                // Add new receiver if it does not exist
                floor[dataType].push(data);
                savebuttondiv.appendChild(saveButton);
                return true;
              } else {
                console.log(`'${dataType}' with the name '${tmpname}' already exists on ${floorName}.`);
                alert(`Ya existe '${tmpname}' en '${floorName}'.`);
                buttonreset();
                clearCanvas();
                drawElements();
                return false;
              }
        } else {
            console.log(`Floor with name '${floorName}' not found.`);
            return false;
        }
      }

    // =================================================================
    // Draw elements on canvas
    // =================================================================

    function scaleStatus(value){
        if(value == null){
            document.getElementById("scalenok").style.display = "flex";
            document.getElementById("scaleok").style.display = "none";
        } else {
            document.getElementById("scalenok").style.display = "none";
            document.getElementById("scaleok").style.display = "flex";
        }
    }

    function drawElements(xp, yp, type){
        const rect = canvas.getBoundingClientRect();
        const tmpdrawcords = [];
        const iconSize = canvas.width * 0.04; // Adjust size as needed
        deleteButton.remove();

        // Beräkna skalning mellan CSS-storlek och ritningsstorlek
        const scaleX = canvas.width / rect.width; // Horisontal scale
        const scaleY = canvas.height / rect.height; // Vertical scale

        if (
            Number.isFinite(xp)
            && Number.isFinite(yp)
            && type === "receiver"
        ) {
            const x = (xp - rect.left) * scaleX;
            const y = (yp - rect.top) * scaleY;
            tmpcords = { x, y };
            tmpdrawcords.push({
                entity_id: receiverName,
                type: type,
                cords: tmpcords,
            });
        }

        let floor = finalcords.floor.find(floor => floor.name === SelMapName); //Add all existing

        if (floor) {
            ensureFloorDefaults(floor);
            myScaleVal = floor.scale; // Get the scalevalue for the floor
            scaleStatus(myScaleVal)//Show or hide status for scale value
            savebuttondiv.appendChild(deleteButton); //If there is data add the delete button to be able to delete the floor.

            if (floor.receivers.length < 3) {
                trackdiv.style.display = "none";
            } else {
                trackdiv.style.display = "";
            }

            // Loopa through all receivers in floor
            floor.receivers.forEach((receiver, index) => {
                ensureReceiverCalibration(receiver);
                receiver.type = "receiver";
                tmpdrawcords.push(receiver);
            });
            // Loopa through all zones in floor
            floor.zones.forEach((zone, index) => {
                zone.type = "zone";
                tmpdrawcords.push(zone);
            });
            floor.walls.forEach((wall, index) => {
                tmpdrawcords.push({
                    ...wall,
                    type: "wall",
                    wall_index: index,
                });
            });
        }

        let tmpHTMLrec = ""; 
        let tmpHTMLzone = "";
        let tmpHTMLwalls = "";
        tmpdrawcords.forEach((item, index) => {

            if (item.type == "receiver"){
                const x = item.cords.x;
                const y = item.cords.y;
                const icon = new Image();
                icon.src = "beacon.svg";
                icon.onload = () => {
                    ctx.drawImage(icon, x - iconSize / 2, y - iconSize / 2, iconSize, iconSize);
                };

                // Show id for receiver
                ctx.font = "bold 25px Arial";
                ctx.fillStyle = "black";
                ctx.fillText(item.entity_id, x + iconSize / 2 + 5, y);
                if(item.entity_id){
                    const factorLabel = Number(item.calibration?.factor ?? 1).toFixed(2);
                    const offsetLabel = Number(item.calibration?.offset ?? 0).toFixed(2);
                    const recLabel = `${item.entity_id} (x${factorLabel}, ${offsetLabel}m)`;
                    tmpHTMLrec = tmpHTMLrec + newelement.replace("typename", recLabel).replace("removexxx", "removerec").replace("idxxx", item.entity_id).replace("idxxx", item.entity_id);
                }
            }
            if (item.type == "zone"){
                const x = item.cords[0].x;
                const y = item.cords[0].y;
                const w = item.cords[1].x - x;
                const h = item.cords[2].y - y;
                
                // Draw rectangle
                ctx.beginPath();
                ctx.rect(x, y, w, h);
                ctx.strokeStyle = "red";
                ctx.lineWidth = 2;
                ctx.stroke();

                // Show id for Zone
                ctx.font = "25px Arial";
                ctx.fillStyle = "red";
                ctx.fillText(item.entity_id, x + 10, y + iconSize / 4);
                if(item.entity_id){
                    tmpHTMLzone = tmpHTMLzone + newelement.replace("typename", item.entity_id).replace("removexxx", "removezone").replace("idxxx", item.entity_id).replace("idxxx", item.entity_id);
                }
            }
            if (item.type == "wall") {
                ctx.beginPath();
                ctx.moveTo(item.x1, item.y1);
                ctx.lineTo(item.x2, item.y2);
                ctx.strokeStyle = "#111827";
                ctx.lineWidth = 4;
                ctx.stroke();
                const wallLabel = `Pared ${item.wall_index + 1}`;
                tmpHTMLwalls += `
                    <ul class="space-y-2" id="wall_${item.wall_index}">
                        <li class="flex items-center justify-between bg-gray-50 p-2 rounded">
                            <span class="text-sm truncate">${wallLabel}</span>
                            <div class="flex gap-2">
                                <button data-type="removewall" data-index="${item.wall_index}" class="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium hover:bg-accent hover:text-accent-foreground w-10">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-trash w-4 h-4"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                                </button>
                            </div>
                        </li>
                    </ul>
                `;
            }
        });

        if (proCalibrationPoint && proCalibrationPoint.floor === SelMapName) {
            const markerSize = canvas.width * 0.035;
            const px = proCalibrationPoint.x;
            const py = proCalibrationPoint.y;
            const icon = new Image();
            icon.src = "person.svg";
            icon.onload = () => {
                ctx.drawImage(icon, px - markerSize / 2, py - markerSize / 2, markerSize, markerSize);
            };
        }

        if(tmpHTMLrec !== ""){
            document.getElementById('divrec').innerHTML = tmpHTMLrec;
        } else{
            document.getElementById('divrec').innerHTML = '<p class="text-sm text-gray-500">No hay receptores colocados</p>';
        }
        if(tmpHTMLzone !== ""){
            document.getElementById('divzones').innerHTML = tmpHTMLzone;
        } else{
            document.getElementById('divzones').innerHTML = '<p class="text-sm text-gray-500">No hay zonas dibujadas</p>';
        }
        if(tmpHTMLwalls !== ""){
            document.getElementById('divwalls').innerHTML = tmpHTMLwalls;
        } else{
            document.getElementById('divwalls').innerHTML = '<p class="text-sm text-gray-500">No hay paredes dibujadas</p>';
        }
        refreshCalibrationSelectors();

    }

    // Display selected map
    mapSelector.addEventListener('change', async () => {
        img.src = `/local/bps_maps/${mapSelector.value}`;
        imgfilename = mapSelector.value;
        mapname.value = removeExtension(mapSelector.value);
        SelMapName = mapname.value;
        await setupCanvasWithImage(img, canvas);
        new_floor = false;
        drawElements();
        if (proCalibrationPoint && proCalibrationPoint.floor === SelMapName) {
            updateProStatus("Pro: posición real marcada para esta planta.");
        } else {
            updateProStatus("Pro: pendiente de marcar posición.");
        }
    });

    upload.addEventListener('change', event => {
        const file = event.target.files[0];
        if (!file) return;
    
        const reader = new FileReader();
        reader.onload = function () {
            img.src = reader.result;
            setupCanvasWithImage(img, canvas);
        };
        reader.readAsDataURL(file);
        new_floor = true;
    });

    function setupCanvasWithImage(img, canvas) {
        return new Promise((resolve) => {
            const ctx = canvas.getContext('2d');
            
            img.onload = () => {
                setupImageSize(img, canvas);
                resolve(); // Resolve when completed
            };
    
            // Add the buttons
            drawAreaButton.className = 'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&amp;_svg]:pointer-events-none [&amp;_svg]:size-4 [&amp;_svg]:shrink-0 border border-input bg-background hover:bg-accent hover:text-accent-foreground h-10 px-4 py-2';
            drawAreaButton.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-pencil w-4 h-4 mr-2" data-component-name="Pencil"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"></path><path d="m15 5 4 4"></path></svg>
                    Dibujar zona
                `;
            drawAreaButton.setAttribute('data-active', 'false');

            drawWallButton.className = 'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&amp;_svg]:pointer-events-none [&amp;_svg]:size-4 [&amp;_svg]:shrink-0 border border-input bg-background hover:bg-accent hover:text-accent-foreground h-10 px-4 py-2';
            drawWallButton.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-panel-top w-4 h-4 mr-2"><path d="M3 3h18"></path><path d="M4 3h16v18H4z"></path></svg>
                    Dibujar pared
                `;
            drawWallButton.setAttribute('data-active', 'false');

            addDeviceButton.className = 'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 border border-input bg-background hover:bg-accent hover:text-accent-foreground h-10 px-4 py-2';
            addDeviceButton.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-radio w-4 h-4 mr-2" data-component-name="Radio"><path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"></path><path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"></path><circle cx="12" cy="12" r="2"></circle><path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"></path><path d="M19.1 4.9C23 8.8 23 15.1 19.1 19"></path></svg>
                    Colocar receptor
                `;
            addDeviceButton.setAttribute('data-active', 'false');

            SetScaleButton.className = 'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 border border-input bg-background hover:bg-accent hover:text-accent-foreground h-10 px-4 py-2';
            SetScaleButton.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-ruler w-4 h-4 mr-2" data-component-name="Ruler"><path d="M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.41 2.41 0 0 1 0-3.4l2.6-2.6a2.41 2.41 0 0 1 3.4 0Z"></path><path d="m14.5 12.5 2-2"></path><path d="m11.5 9.5 2-2"></path><path d="m8.5 6.5 2-2"></path><path d="m17.5 15.5 2-2"></path></svg>
                    Establecer escala
                `;
            SetScaleButton.setAttribute('data-active', 'false');
            
            clearCanvasButton.className = 'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 border border-input bg-background hover:bg-accent hover:text-accent-foreground h-10 px-4 py-2';
            clearCanvasButton.innerHTML = `
                <svg width="24px" height="24px" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M9 9L15 15" stroke="#000000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M15 9L9 15" stroke="#000000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="12" r="9" stroke="#000000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                    Limpiar lienzo
                `;
            
            saveButton.className = 'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&amp;_svg]:pointer-events-none [&amp;_svg]:size-4 [&amp;_svg]:shrink-0 bg-primary text-primary-foreground hover:bg-primary/90 h-10 px-4 py-2';
            saveButton.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-save w-4 h-4 mr-2" data-component-name="Save"><path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"></path><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"></path><path d="M7 3v4a1 1 0 0 0 1 1h7"></path></svg>
                    Guardar plano
                `;
            
            mapbuttondiv.appendChild(addDeviceButton);
            mapbuttondiv.appendChild(drawAreaButton);
            mapbuttondiv.appendChild(drawWallButton);
            mapbuttondiv.appendChild(SetScaleButton);
            mapbuttondiv.appendChild(clearCanvasButton);
        });
    }


    function setupImageSize(img, canvas, fixedWidth = 2000) {
        const ctx = canvas.getContext('2d');
    
        const imgratio = img.height / img.width;
        const newwidth = fixedWidth; // Fixed width in pixels
        const newheight = newwidth * imgratio; // Height based on aspect ratio
    
        // Update canvas size
        canvas.width = newwidth;
        canvas.height = newheight;
    
        // Draw image on canvas
        ctx.drawImage(img, 0, 0, newwidth, newheight);
    }
    

    function removeExtension(fileName) {
        const lastDotIndex = fileName.lastIndexOf('.');
        if (lastDotIndex === -1) {
            return fileName;
        }
        return fileName.substring(0, lastDotIndex);
    }

    // Save data
    saveButton.addEventListener('click', async () => {
        let saveresult = await savedata();
        if(saveresult){
            tmpfinalcords = finalcords;
            saveButton.remove();
            alert('Guardado correctamente.');
            getSavedMaps();
        }
    });

    //When clicking the delete button, remove the floor and reset the canvas.
    deleteButton.addEventListener("click", async function () {
        const userConfirmed = confirm("¿Seguro que quieres eliminar la planta "+SelMapName+"?");
        let tmpfinal = JSON.parse(JSON.stringify(finalcords)); //Save the array to a temporary

        if (userConfirmed) {
            finalcords.floor = finalcords.floor.filter(floor => floor.name !== SelMapName); // Remove the selected floor
            removefile = true;
            let saveresult = await savedata();
            if(saveresult){
                alert("Se ha eliminado la planta "+SelMapName+".");
                console.log("Updated data:", finalcords); // Control the updated data
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                mapname.value = "";
                getSavedMaps();
            } else {
                finalcords = tmpfinal; //If not able to delete, restore the array
            }
        } else {
            alert("Acción cancelada. No se aplicaron cambios.");
            finalcords = tmpfinal;
        }
    });

    async function savedata(){
        if (!(removefile === true && new_floor === false)) {
            const floor = getCurrentFloor();
            if (!floor || !Number.isFinite(Number(floor.scale)) || Number(floor.scale) <= 0) {
                alert("No has definido la escala. Sin escala no funcionará.");
                return;
            }
            myScaleVal = Number(floor.scale);
        }
        
        removeListeners();
        const data = new FormData();
        data.append('coordinates', JSON.stringify(finalcords)); 
        data.append('new_floor', new_floor);

        if(removefile === true && new_floor === false){
            data.append('remove', imgfilename);
        }

        if(new_floor){ // Add filedata to variable 'data' if there is a new floor
            const file = upload.files[0];
            const extension = file.name.substring(file.name.lastIndexOf('.')); // Get the old file ending
            const newFileName = `${SelMapName}${extension}`; // Build the new filename
            const renamedFile = new File([file], newFileName, { type: file.type });

            if (renamedFile) {
                data.append('file', renamedFile);
            } else {
                console.log("No file uploaded.");
            }
        }

        try {
            const response = await fetch('/api/bps/save_text', {
                method: 'POST',
                body: data,
            });
            if (response.ok) {
                drawAreaButton.remove();
                drawWallButton.remove();
                addDeviceButton.remove();
                clearCanvasButton.remove();
                SetScaleButton.remove();
                saveButton.remove();
                new_floor = false;
                return true;
            } else {
                alert('Error al guardar los datos.');
            }
        } catch (error) {
            console.error('Error saving data:', error);
            alert('Error al guardar los datos.');
        }
    }

});
