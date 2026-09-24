const XLSX = require('xlsx');
const path = require('path');

const companies = [
  ['ABC Pharma', 'https://abcpharma.com', 'Pharma', 'India'],
  ['XYZ Health', 'https://xyzhealth.com', 'Healthcare', 'India'],
  ['Tech Solutions Inc', 'https://techsolutions.com', 'Technology', 'USA'],
  ['Global Enterprises', 'https://globalent.com', 'Manufacturing', 'UK'],
  ['DataFlow Analytics', 'https://dataflow.io', 'Technology', 'USA'],
  ['MediCare Plus', 'https://medicareplus.com', 'Healthcare', 'India'],
  ['Sunrise Industries', 'https://sunriseind.com', 'Manufacturing', 'India'],
  ['CloudFirst Systems', 'https://cloudfirst.io', 'Technology', 'USA'],
  ['HealthBridge Corp', 'https://healthbridge.com', 'Healthcare', 'UK'],
  ['GreenEnergy Ltd', 'https://greenenergy.com', 'Energy', 'Germany'],
  ['FinServe Global', 'https://finserveglobal.com', 'Finance', 'Singapore'],
  ['RetailMax Group', 'https://retailmax.com', 'Retail', 'USA'],
  ['EduTech Solutions', 'https://edutech.io', 'Education', 'Canada'],
  ['LogiTrack Inc', 'https://logitrack.com', 'Logistics', 'USA'],
  ['BioGenesis Labs', 'https://biogenesis.com', 'Biotech', 'Switzerland'],
  ['SmartCity Corp', 'https://smartcity.com', 'Real Estate', 'UAE'],
  ['AgriTech Ventures', 'https://agritech.io', 'Agriculture', 'India'],
  ['CyberShield Security', 'https://cybershield.com', 'Cybersecurity', 'Israel'],
  ['AutoDrive Systems', 'https://autodrive.io', 'Automotive', 'Germany'],
  ['AeroSpace Dynamics', 'https://aerospace.com', 'Aerospace', 'USA'],
  ['FoodChain Global', 'https://foodchain.com', 'Food & Beverage', 'Netherlands'],
  ['OceanFreight Ltd', 'https://oceanfreight.com', 'Shipping', 'Singapore'],
  ['PharmaVet Corp', 'https://pharmavet.com', 'Pharma', 'India'],
  ['CleanWater Systems', 'https://cleanwater.com', 'Environmental', 'USA'],
  ['NextGen Robotics', 'https://nextgenrobotics.io', 'Technology', 'Japan'],
  ['PrimeHealth Hospitals', 'https://primehealth.com', 'Healthcare', 'India'],
  ['Quantum Computing Inc', 'https://quantumcomp.io', 'Technology', 'USA'],
  ['SolarTech Energy', 'https://solartech.com', 'Energy', 'Australia'],
  ['UrbanLiving Properties', 'https://urbanliving.com', 'Real Estate', 'UK'],
  ['MedDevice Solutions', 'https://meddevice.com', 'Medical Devices', 'USA'],
  ['SteelBridge Industries', 'https://steelbridge.com', 'Manufacturing', 'India'],
  ['DigitalPayments Co', 'https://digitalpay.io', 'FinTech', 'Sweden'],
  ['AquaPure Systems', 'https://aquapure.com', 'Environmental', 'Canada'],
  ['CloudNine Services', 'https://cloudnine.io', 'Technology', 'India'],
  ['TeleHealth Connect', 'https://telehealthconnect.com', 'Healthcare', 'USA'],
  ['PrecisionAero Ltd', 'https://precisionaero.com', 'Aerospace', 'France'],
  ['GreenLogistics Co', 'https://greenlogistics.com', 'Logistics', 'Germany'],
  ['BioPharm Innovations', 'https://biopharm.io', 'Pharma', 'Switzerland'],
  ['SmartGrid Energy', 'https://smartgrid.com', 'Energy', 'USA'],
  ['DigitalTwin Systems', 'https://digitaltwin.io', 'Technology', 'Germany'],
  ['ElderCare Plus', 'https://eldercareplus.com', 'Healthcare', 'UK'],
  ['RoboFactory Inc', 'https://robofactory.io', 'Manufacturing', 'Japan'],
  ['InsurTech Global', 'https://insurtechglobal.com', 'Insurance', 'USA'],
  ['CleanFuel Solutions', 'https://cleanfuel.com', 'Energy', 'Norway'],
  ['DataVault Security', 'https://datavault.io', 'Cybersecurity', 'Israel'],
  ['SmartFarm Agriculture', 'https://smartfarm.io', 'Agriculture', 'Brazil'],
  ['AIHealth Diagnostics', 'https://aihealth.com', 'Healthcare', 'USA'],
  ['HyperLoop Transit', 'https://hyperlooptransit.com', 'Transportation', 'USA'],
  ['NanoTech Materials', 'https://nanotech.com', 'Manufacturing', 'South Korea'],
  ['VirtualCare Platform', 'https://virtualcare.io', 'Healthcare', 'Canada'],
  ['SpaceTech Ventures', 'https://spacetech.io', 'Aerospace', 'USA'],
];

const wb = XLSX.utils.book_new();
const ws = XLSX.utils.aoa_to_sheet([
  ['Company Name', 'Website', 'Industry', 'Country'],
  ...companies
]);
XLSX.utils.book_append_sheet(wb, ws, 'Companies');
XLSX.writeFile(wb, path.join(__dirname, '..', 'test-companies.xlsx'));

console.log(`Created test file with ${companies.length} companies`);
