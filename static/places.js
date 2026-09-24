function createPlacePicker(dialog,event) {
  const root=dialog.querySelector('#place-picker');
  let selected=event?.latitude!=null?{location:event.location,address:event.address,latitude:event.latitude,longitude:event.longitude}:null;
  let manual=Boolean(event&&!selected), map=null, marker=null, results=[], revision=0, destroyed=false, pinned=false;
  root.innerHTML=`<label for="place-query" class="place-label">Location</label><div class="place-selected" hidden></div>
    <div class="place-search-area"><div class="place-search-bar"><input id="place-query" type="search" maxlength="160" autocomplete="off" aria-label="Search courts or places"><button type="button" class="icon-button" data-place-search aria-label="Search places" title="Search places">${icon('search')}</button></div><p class="place-status" role="status"></p><div class="place-results"></div><div class="place-options"><button type="button" data-place-map>Choose on map</button><button type="button" data-place-manual>Enter manually</button></div></div>
    <div class="place-manual" ${manual?'':'hidden'}><div class="plan-field"><label for="plan-location">Name</label><input id="plan-location" name="location" maxlength="120" value="${esc(event?.location||'')}"></div><div class="plan-field"><label for="plan-address">Address</label><input id="plan-address" name="address" maxlength="200" value="${esc(event?.address||'')}"></div><button type="button" class="place-change" data-place-change>Search places</button></div>
    <div class="place-pin-name" hidden><label for="pin-name">Court name</label><input id="pin-name" maxlength="120"></div>
    <div class="place-map-area" hidden><div class="place-map-tools"><button type="button" data-place-near>Near me</button><button type="button" data-place-center>Use map center</button><button type="button" data-place-hide>Close map</button></div><div class="place-map" aria-label="Choose a court location on the map"></div><p class="place-map-status" role="status"></p></div>`;
  const searchArea=root.querySelector('.place-search-area'),summary=root.querySelector('.place-selected'),query=root.querySelector('#place-query');
  const manualArea=root.querySelector('.place-manual'),status=root.querySelector('.place-status'),list=root.querySelector('.place-results');
  const mapArea=root.querySelector('.place-map-area'),mapStatus=root.querySelector('.place-map-status');
  const nameInput=root.querySelector('#plan-location'),addressInput=root.querySelector('#plan-address');

  function showSelection(place,isPin=false) {
    revision++;selected={...place};pinned=isPin;manual=false;manualArea.hidden=true;searchArea.hidden=true;summary.hidden=false;
    root.querySelector('.place-pin-name').hidden=!pinned;
    root.querySelector('#pin-name').value=place.location;
    summary.innerHTML=`<div><strong>${esc(place.location)}</strong><span>${esc(place.address||`${place.latitude.toFixed(5)}, ${place.longitude.toFixed(5)}`)}</span></div><div class="place-options"><button type="button" data-place-change>Change</button><button type="button" data-place-map>Map</button></div>`;
    if(map){if(marker)marker.setLatLng([place.latitude,place.longitude]);else marker=L.marker([place.latitude,place.longitude]).addTo(map);if(!isPin)map.setView([place.latitude,place.longitude],16);}
  }

  function showResults(places,recent=false) {
    results=places;
    list.innerHTML=`${recent&&places.length?'<span class="place-recent-label">Recent places</span>':''}<ul>${places.map((p,i)=>`<li><button type="button" data-place-result="${i}"><strong>${esc(p.location)}</strong><span>${esc(p.address)}</span></button></li>`).join('')}</ul>${!recent?'<p class="place-attribution">Search by Photon · © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a></p>':''}`;
  }

  async function search() {
    const value=query.value.trim();
    if(value.length<3){status.textContent='Enter a place name or city.';query.focus();return;}
    const request=++revision,button=root.querySelector('[data-place-search]');button.disabled=true;status.textContent='Searching…';list.innerHTML='';
    try {
      const result=await api('/places/search',jsonRequest('POST',{query:value}));
      if(destroyed||request!==revision)return;
      showResults(result.places);status.textContent=result.places.length?'':'No matches. Try adding a city, or choose a point on the map.';
      if(map&&result.places.length&&!selected)map.setView([result.places[0].latitude,result.places[0].longitude],12);
    }catch(error){if(!destroyed&&request===revision)status.textContent=error.message;}
    finally{if(!destroyed)button.disabled=false;}
  }

  function choosePin(latlng) {
    const point=latlng.wrap();
    showSelection({location:'Pinned court',address:'',latitude:Math.max(-90,Math.min(90,point.lat)),longitude:point.lng},true);
    mapStatus.textContent='Pin selected';
  }

  function openMap() {
    mapArea.hidden=false;
    if(!window.L){mapStatus.textContent='Map could not load. You can still search or enter a place manually.';return;}
    if(!map){
      const center=selected||results.find(p=>p.latitude!=null);
      map=L.map(root.querySelector('.place-map'),{scrollWheelZoom:false}).setView(center?[center.latitude,center.longitude]:[20,0],center?15:2);
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{
        maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>',
        updateWhenIdle:true,keepBuffer:0
      }).on('tileerror',()=>{mapStatus.textContent='Some map tiles could not load. Search or manual entry is still available.';}).addTo(map);
      map.on('click',e=>choosePin(e.latlng));
      if(selected)marker=L.marker([selected.latitude,selected.longitude]).addTo(map);
    }
    requestAnimationFrame(()=>{if(!destroyed){map.invalidateSize();mapArea.scrollIntoView({block:'nearest'});}});
  }

  root.addEventListener('click',async e=>{
    const button=e.target.closest('button');if(!button)return;
    if(button.hasAttribute('data-place-search'))await search();
    if(button.dataset.placeResult!==undefined){
      const place=results[Number(button.dataset.placeResult)];
      if(place.latitude!=null)showSelection(place);
      else{selected=null;manual=true;manualArea.hidden=false;searchArea.hidden=true;nameInput.value=place.location;addressInput.value=place.address;}
    }
    if(button.hasAttribute('data-place-manual')){revision++;selected=null;manual=true;manualArea.hidden=false;searchArea.hidden=true;mapArea.hidden=true;nameInput.focus();}
    if(button.hasAttribute('data-place-change')){revision++;selected=null;manual=false;pinned=false;summary.hidden=true;manualArea.hidden=true;searchArea.hidden=false;root.querySelector('.place-pin-name').hidden=true;query.focus();}
    if(button.hasAttribute('data-place-map'))openMap();
    if(button.hasAttribute('data-place-hide'))mapArea.hidden=true;
    if(button.hasAttribute('data-place-center')&&map)choosePin(map.getCenter());
    if(button.hasAttribute('data-place-near')&&map){
      if(!navigator.geolocation){mapStatus.textContent='Location is unavailable. Search for a city instead.';return;}
      button.disabled=true;mapStatus.textContent='Finding your location…';
      navigator.geolocation.getCurrentPosition(position=>{if(!destroyed){map.setView([position.coords.latitude,position.coords.longitude],16);mapStatus.textContent='';button.disabled=false;}},()=>{if(!destroyed){mapStatus.textContent='Location unavailable. Search for a city instead.';button.disabled=false;}},{timeout:10000,maximumAge:60000});
    }
  });
  query.addEventListener('input',()=>{revision++;status.textContent='';list.innerHTML='';});
  query.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();search();}if(e.key==='ArrowDown'){e.preventDefault();list.querySelector('button')?.focus();}});
  root.querySelector('#pin-name').addEventListener('input',e=>{if(pinned&&selected){selected.location=e.target.value;summary.querySelector('strong').textContent=e.target.value;}});
  if(selected)showSelection(selected);
  else if(manual)searchArea.hidden=true;
  else api('/places/recent').then(result=>{if(!destroyed&&!selected&&!manual&&!query.value)showResults(result.places,true);}).catch(()=>{});
  return {
    focus(){(manual?nameInput:selected?summary.querySelector('button'):query).focus();},
    value(){
      const place=manual?{location:nameInput.value.trim(),address:addressInput.value.trim(),latitude:null,longitude:null}:selected;
      if(!place?.location?.trim())throw Error(manual?'Enter a court name.':'Choose a place, drop a pin, or enter a location manually.');
      return place;
    },
    destroy(){destroyed=true;revision++;map?.remove();}
  };
}
