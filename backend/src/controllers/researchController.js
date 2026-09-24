const mongoose = require('mongoose');
const Company = require('../models/Company');
const { runCompanyResearch, getCompanyResearch } = require('../services/researchService');

const triggerResearch = async (req, res, next) => {
  try {
    const { companyId } = req.params;

    if (!companyId || !mongoose.Types.ObjectId.isValid(companyId)) {
      return res.status(400).json({
        success: false,
        message: 'Invalid company ID'
      });
    }

    const company = await Company.findById(companyId);
    if (!company) {
      return res.status(404).json({
        success: false,
        message: 'Company not found'
      });
    }

    const research = await runCompanyResearch(companyId);
    res.json({
      success: true,
      message: 'AI research generated successfully',
      data: research
    });
  } catch (err) {
    next(err);
  }
};

const getResearch = async (req, res, next) => {
  try {
    const { companyId } = req.params;

    if (!companyId || !mongoose.Types.ObjectId.isValid(companyId)) {
      return res.status(400).json({
        success: false,
        message: 'Invalid company ID'
      });
    }

    const company = await Company.findById(companyId);
    if (!company) {
      return res.status(404).json({
        success: false,
        message: 'Company not found'
      });
    }

    const research = await getCompanyResearch(companyId);
    
    // When company exists but no research has been generated yet, return 200 with data: null
    return res.status(200).json({
      success: true,
      data: research || null,
      message: research ? 'Company research retrieved successfully' : 'No research found for this company. Please run research first.'
    });
  } catch (err) {
    next(err);
  }
};

module.exports = {
  triggerResearch,
  getResearch
};
