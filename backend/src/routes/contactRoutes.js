const express = require('express');
const router = express.Router({ mergeParams: true });
const {
  listContacts,
  addContact,
  editContact,
  removeContact,
  discoverContacts,
  verifyContact,
  getPatternInfo,
  applyPattern
} = require('../controllers/contactController');

// Company-nested routes (e.g. /api/companies/:companyId/contacts/pattern)
router.get('/contacts/pattern', getPatternInfo);
router.post('/contacts/apply-pattern', applyPattern);
router.get('/contacts', listContacts);
router.post('/contacts', addContact);
router.post('/contacts/discover', discoverContacts);
router.put('/contacts/:contactId', editContact);
router.delete('/contacts/:contactId', removeContact);
router.post('/contacts/:contactId/verify', verifyContact);

// Direct contact-level routes (e.g. /api/contacts/:contactId)
router.get('/pattern', getPatternInfo);
router.post('/apply-pattern', applyPattern);
router.get('/', listContacts);
router.post('/', addContact);
router.put('/:contactId', editContact);
router.delete('/:contactId', removeContact);
router.post('/:contactId/verify', verifyContact);

module.exports = router;
