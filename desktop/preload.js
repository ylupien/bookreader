// Pont minimal : l'interface web n'a besoin d'aucune API Node pour l'instant.
const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('bookreaderDesktop', { isDesktop: true });
