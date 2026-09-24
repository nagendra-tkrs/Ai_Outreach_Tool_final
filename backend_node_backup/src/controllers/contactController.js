const {
  getCompanyContacts,
  createContact,
  updateContact,
  deleteContact,
  extractContactsFromWebsite,
  verifyContactEmail,
  getCompanyEmailPatternInfo,
  applyPatternToContacts
} = require('../services/contactService');

const listContacts = async (req, res, next) => {
  try {
    const { companyId } = req.params;
    const contacts = await getCompanyContacts(companyId);
    res.json({
      success: true,
      data: contacts
    });
  } catch (err) {
    next(err);
  }
};

const addContact = async (req, res, next) => {
  try {
    const { companyId } = req.params;
    const contact = await createContact(companyId, req.body);
    res.status(201).json({
      success: true,
      message: 'Contact created successfully',
      data: contact
    });
  } catch (err) {
    next(err);
  }
};

const editContact = async (req, res, next) => {
  try {
    const { contactId } = req.params;
    const contact = await updateContact(contactId, req.body);
    res.json({
      success: true,
      message: 'Contact updated successfully',
      data: contact
    });
  } catch (err) {
    next(err);
  }
};

const removeContact = async (req, res, next) => {
  try {
    const { contactId } = req.params;
    const result = await deleteContact(contactId);
    res.json({
      success: true,
      message: result.message
    });
  } catch (err) {
    next(err);
  }
};

const { getActiveSearchProviderConfig } = require('../services/search/searchProvider');

const discoverContacts = async (req, res, next) => {
  try {
    const { companyId } = req.params;
    const contacts = await extractContactsFromWebsite(companyId);
    const decisionMakers = contacts.filter(c => c.roleCategory !== 'general' && c.seniority !== 'general');
    const selectedDecisionMaker = decisionMakers.find(c => c.isPrimaryDecisionMaker) || decisionMakers[0] || null;
    const decisionMakerStatus = selectedDecisionMaker ? selectedDecisionMaker.decisionMakerStatus : 'NOT_VERIFIED';
    const searchConfig = getActiveSearchProviderConfig();

    console.log(`[EMAIL-DEBUG][17] Final status:
Selected Decision Maker: ${selectedDecisionMaker?.name || 'None'}
Email: ${selectedDecisionMaker?.email || 'None'}
Email Status: ${selectedDecisionMaker?.emailStatus || 'None'}
Email Pattern: ${selectedDecisionMaker?.patternUsed || selectedDecisionMaker?.emailPattern || 'None'}
Corporate Domain: ${selectedDecisionMaker?.emailDomain || 'None'}`);

    res.json({
      success: true,
      message: 'Contacts extracted successfully',
      data: contacts,
      decisionMakers,
      selectedDecisionMaker,
      decisionMakerStatus,
      searchDiagnostics: {
        provider: searchConfig.providerName || 'none',
        isConfigured: Boolean(searchConfig.isConfigured),
        reason: searchConfig.reason || (searchConfig.isConfigured ? 'READY' : 'SEARCH_PROVIDER_NOT_CONFIGURED')
      }
    });
  } catch (err) {
    next(err);
  }
};

const verifyContact = async (req, res, next) => {
  try {
    const { contactId } = req.params;
    const contact = await verifyContactEmail(contactId);
    res.json({
      success: true,
      message: 'Contact email verified successfully',
      data: contact
    });
  } catch (err) {
    next(err);
  }
};

const getPatternInfo = async (req, res, next) => {
  try {
    const { companyId } = req.params;
    const patternData = await getCompanyEmailPatternInfo(companyId);
    console.log(`[EMAIL-DEBUG][20] Exact API response sent to frontend (getPatternInfo):`, JSON.stringify(patternData));
    res.json({
      success: true,
      data: patternData
    });
  } catch (err) {
    next(err);
  }
};

const applyPattern = async (req, res, next) => {
  try {
    const { companyId } = req.params;
    const { pattern } = req.body;
    const result = await applyPatternToContacts(companyId, pattern);
    res.json({
      success: true,
      message: 'Email format applied to decision makers',
      data: result
    });
  } catch (err) {
    next(err);
  }
};

module.exports = {
  listContacts,
  addContact,
  editContact,
  removeContact,
  discoverContacts,
  verifyContact,
  getPatternInfo,
  applyPattern
};
