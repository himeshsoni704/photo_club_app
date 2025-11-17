import java.util.*;

class exp {
    public static void main(String args[]) {
        
        int a = Integer.parseInt(args[0]);  
        
        try {
            a = a / 0;  
        }
        catch(ArrayIndexOutOfBoundsException e) {  
            System.out.println("Exception caught: " + e);
        }
        finally {
            System.out.println("Finally block executed.");
        }
        
        System.out.println("Value of a: " + a);  
    }
}