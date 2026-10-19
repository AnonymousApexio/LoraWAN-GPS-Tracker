// Downlink payload formatter (Custom JavaScript formatter)
// Transforme un ordre lisible en octets a envoyer par radio.
//   { "commande": "stop" }   -->   01   (un seul octet, FPort 1)
function encodeDownlink(input) {
  var commande = input.data && input.data.commande;
  if (commande === "stop") {
    return { bytes: [0x01], fPort: 1 };
  }
  return { errors: ["commande inconnue : " + commande] };
}

// Operation inverse : permet au LNS d'afficher le downlink en clair dans le Live data.
function decodeDownlink(input) {
  if (input.bytes.length === 1 && input.bytes[0] === 0x01) {
    return { data: { commande: "stop" } };
  }
  return { errors: ["downlink inconnu"] };
}