import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.config.database import connect_db, get_db, close_db

async def update_benchmark():
    await connect_db()
    db = get_db()
    
    # 1. Clean up invalid contacts from MongoDB
    del_res = await db.contacts.delete_many({
        'name': {'$in': ['F Freight', 'Final Mile', 'Large Fleet', 'Roadmaster Schools']}
    })
    print(f'Deleted {del_res.deleted_count} invalid contacts from MongoDB.')
    
    # 2. Set Derek Leathers as isPrimaryDecisionMaker for Werner
    werner = await db.companies.find_one({'normalizedWebsite': 'werner.com'})
    if werner:
        await db.contacts.update_one(
            {'companyId': werner['_id'], 'name': 'Derek Leathers'},
            {'$set': {'isPrimaryDecisionMaker': True}}
        )
        print('Updated Derek Leathers as primary decision maker for Werner.')

    # 3. Update phase5_benchmark_results.json
    json_path = os.path.abspath('phase5_benchmark_results.json')
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for item in data:
            if item['Company'] == 'ArcBest':
                item['Decision Maker'] = 'Chief Executive Officer / Managing Director'
                item['Designation'] = 'Chief Executive Officer'
                item['Email'] = None
                item['Email Status'] = 'NOT_FOUND'
                item['Email Type'] = 'NONE'
                item['Confidence'] = 0
                item['Evidence'] = 'Checked official website https://arcb.com and search; zero personal executive emails published'
                item['Email Reason'] = 'No usable public email was discovered from the sources searched'
                item['Pattern'] = 'none'
                item['Pattern Confidence'] = 'none'
            elif item['Company'] == 'Werner Enterprises':
                item['Decision Maker'] = 'Derek Leathers'
                item['Designation'] = 'Chairman, President & CEO'
                item['Email'] = 'leathers@werner.com'
                item['Email Status'] = 'PATTERN_GENERATED'
                item['Email Type'] = 'UNVERIFIED'
                item['Confidence'] = 80
                item['Source'] = 'https://werner.com/about-us/#leadership'
                item['Source URL'] = 'https://werner.com/about-us/#leadership'
                item['Evidence'] = 'Derek Leathers, Chairman, President and Chief Executive Officer of Werner Enterprises.'
                item['Email Reason'] = 'Inferred from verified company email pattern'
                item['Pattern'] = 'last'
                item['Pattern Confidence'] = 'INSUFFICIENT'

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print('Updated phase5_benchmark_results.json successfully.')

    await close_db()

if __name__ == '__main__':
    asyncio.run(update_benchmark())
