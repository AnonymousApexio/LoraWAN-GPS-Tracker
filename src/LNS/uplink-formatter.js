// Uplink payload formatter (Custom JavaScript formatter)
// Decode les 6 octets envoyes par encode_position() du LoPy.
function decodeUplink(input) {
  var b = input.bytes;

  if (b.length !== 6) {
    return { errors: ["6 octets attendus, " + b.length + " recus"] };
  }

  var latRaw = (b[0] << 16) | (b[1] << 8) | b[2];
  var lonRaw = (b[3] << 16) | (b[4] << 8) | b[5];

  var lat = latRaw / 16777215 * 180 - 90;
  var lon = lonRaw / 16777215 * 360 - 180;

  return {
    data: {
      lat: Math.round(lat*1e6)/1e6,
      lon: Math.round(lon*1e6)/1e6
    }
  };
}
