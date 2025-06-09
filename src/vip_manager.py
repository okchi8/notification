import csv
import os
import logging

class VIPManager:
    def __init__(self, csv_file_path):
        self.csv_file_path = csv_file_path
        self.vip_data = {}
        self.expected_headers = ['plate_number', 'owner_name', 'house_number', 'land_number', 'chat_id', 'type']
        self._load_vip_list()

    def _load_vip_list(self):
        if not os.path.exists(self.csv_file_path):
            logging.error(f"VIP list file not found: {self.csv_file_path}")
            self.vip_data = {}
            return

        try:
            with open(self.csv_file_path, mode='r', encoding='utf-8', newline='') as csvfile:
                reader = csv.DictReader(csvfile)

                if not reader.fieldnames or not all(header in reader.fieldnames for header in self.expected_headers):
                    logging.error(f"VIP list CSV headers are incorrect or missing. Expected: {self.expected_headers}. Got: {reader.fieldnames}")
                    self.vip_data = {}
                    return

                for row in reader:
                    plate_number_val = row.get('plate_number')
                    if plate_number_val:
                        self.vip_data[plate_number_val.strip().upper()] = {
                            'plate_number': plate_number_val.strip(),
                            'owner_name': row.get('owner_name', '').strip(),
                            'house_number': row.get('house_number', '').strip(),
                            'land_number': row.get('land_number', '').strip(),
                            'chat_id': row.get('chat_id', '').strip(),
                            'type': row.get('type', '').strip()
                        }
                    else:
                        logging.warning(f"Skipping row due to missing plate_number in {self.csv_file_path}: {row}")
                # This logging.info is after the for loop, inside the 'with' and 'try'
                logging.info(f"Successfully loaded {len(self.vip_data)} records from {self.csv_file_path}")
        except Exception as e:
            logging.error(f"Error loading VIP list from {self.csv_file_path}: {e}", exc_info=True)
            self.vip_data = {}

    def get_vip_details(self, plate_number):
        return self.vip_data.get(plate_number.strip().upper())

    def refresh_vip_list(self):
        logging.info("Refreshing VIP list...")
        self._load_vip_list()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    dummy_csv_path = 'temp_test_vip_list.csv'
    new_headers = ['plate_number', 'owner_name', 'house_number', 'land_number', 'chat_id', 'type']
    new_sample_data = [
        new_headers,
        ['ANR9163', 'OKChi', '32', 'C2', '814158826', 'Residence'],
        ['AHH6386', 'OKChi', '32', 'C2', '814158826', 'Visitor'],
        ['WXL5640', 'OKChi', '32', 'C2', '814158826', 'Residence'],
        ['AKN8011', 'Keith', '16', 'C7', '6827525837', 'Residence'],
        ['AKN801', 'Keith', '16', 'C7', '6827525837', 'Residence'],
        ['AHK3396', 'Sam', '28', 'C2', '667240336', 'Residence']
    ]
    with open(dummy_csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(new_sample_data)

    vip_manager = VIPManager(dummy_csv_path)

    print("\nTesting VIP lookups with new headers:")
    test_plates = ['ANR9163', 'ahn801', 'WXL5640', 'UNKNOWNPLATE']
    for plate in test_plates:
        details = vip_manager.get_vip_details(plate)
        if details:
            print(f"  Found VIP: {plate} -> {details}")
        else:
            print(f"  Not a VIP: {plate}")

    print("\nTesting with a malformed CSV (using old headers to simulate wrong format):")
    malformed_csv_path = 'temp_malformed_vip_list.csv'
    with open(malformed_csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['PlateNumber', 'Name', 'HouseNumber', 'Lane', 'ChatID', 'Type'])
        writer.writerow(['DEF5678', 'Bad Data', '303', 'D', 'chat000', 'Invalid'])

    malformed_vip_manager = VIPManager(malformed_csv_path)
    details_malformed = malformed_vip_manager.get_vip_details('DEF5678')
    if not details_malformed and not malformed_vip_manager.vip_data:
        print("  Correctly handled malformed CSV (no data loaded, error logged).")
    else:
        print(f"  Incorrectly handled malformed CSV. Details: {details_malformed}, Loaded VIP Data: {malformed_vip_manager.vip_data}")

    print("\nTesting with a non-existent CSV:")
    non_existent_manager = VIPManager('non_existent_vip_list.csv')
    details_non_existent = non_existent_manager.get_vip_details('ANYPLATE')
    if not details_non_existent and not non_existent_manager.vip_data:
        print("  Correctly handled non-existent CSV (no data loaded, error logged).")
    else:
        print(f"  Incorrectly handled non-existent CSV. Details: {details_non_existent}, Data: {non_existent_manager.vip_data}")

    os.remove(dummy_csv_path)
    os.remove(malformed_csv_path)
    print("\nCleaned up temporary test files.")
