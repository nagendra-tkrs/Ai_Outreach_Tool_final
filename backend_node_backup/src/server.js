const express = require('express');
const cors = require('cors');
require('dotenv').config();

const connectDB = require('./config/database');
const errorHandler = require('./middleware/errorHandler');
const importRoutes = require('./routes/importRoutes');
const companyRoutes = require('./routes/companyRoutes');
const outreachRoutes = require('./routes/outreachRoutes');
const settingsRoutes = require('./routes/settingsRoutes');
const contactRoutes = require('./routes/contactRoutes');
const trackingRoutes = require('./routes/trackingRoutes');
const { startScheduler } = require('./services/schedulerService');

const app = express();

app.use(cors({
  origin: process.env.FRONTEND_URL || 'http://localhost:5173',
  credentials: true
}));
app.use(express.json());

app.get('/api/health', (req, res) => {
  res.json({ success: true, message: 'AI Client Outreach API is running' });
});

app.use('/api/import', importRoutes);
app.use('/api/companies', companyRoutes);
app.use('/api/outreach', outreachRoutes);
app.use('/api/settings', settingsRoutes);
app.use('/api/contacts', contactRoutes);
app.use('/api/track', trackingRoutes);

app.use(errorHandler);

const startServer = async () => {
  await connectDB();
  const PORT = process.env.PORT || 5000;
  app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
    startScheduler(60000);
  });
};

if (require.main === module) {
  startServer();
}

module.exports = { app, startServer };
